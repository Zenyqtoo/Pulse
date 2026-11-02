"""Loopback-only model lab. No database writes, API keys or external inference.

Run in the isolated ML environment. Uses only already-cached model weights.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from threading import Lock
from urllib.parse import urlsplit

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BACKEND))
from app.ai.local_features import combine_features, encoder_texts, texts_for_features, transform_lexical
from app.ai.local_routing import route_predictions
from app.reference import DEPT_NAMES, SENTIMENT_NAMES, TYPE_NAMES
from train_local_model import model_text, predict_heads


def validate_input(payload):
    if not isinstance(payload,dict):
        raise ValueError("Ожидается сообщение")
    text,context,kind = payload.get("text"),payload.get("context",""),payload.get("kind","")
    if not isinstance(text,str) or not text.strip() or len(text)>6000:
        raise ValueError("Введите от 1 до 6000 символов")
    if not isinstance(context,str) or len(context)>2000:
        raise ValueError("Контекст — до 2000 символов")
    if kind not in ("","post","article","comment","reply","message","review"):
        raise ValueError("Неизвестный тип записи")
    return {"text":text,"context":context,"kind":kind}


class LocalModel:
    def __init__(self, model_dir, cache):
        self.payload = json.loads((model_dir/"heads.json").read_text(encoding="utf-8"))
        self.card = json.loads((model_dir/"model_card.json").read_text(encoding="utf-8"))
        self.routed = self.payload['format']=='cityalert-local-experts-v4'
        if self.routed:
            self.general = json.loads((model_dir/self.payload['general_file']).read_text(encoding='utf-8'))
            self.contextual = json.loads((model_dir/self.payload['contextual_file']).read_text(encoding='utf-8'))
        from sentence_transformers import SentenceTransformer
        import torch
        torch.set_num_threads(4)
        self.encoder = SentenceTransformer(self.payload["encoder"],revision=self.payload["encoder_revision"],
            cache_folder=str(cache),local_files_only=True,device="cpu",trust_remote_code=False)
        self.lock = Lock()

    def predict(self,row):
        if self.routed:
            with self.lock:
                embedded = self.encoder.encode([model_text(row),encoder_texts([row],self.contextual['features'])[0]],
                                               normalize_embeddings=True,show_progress_bar=False)
            predictions = []
            for expert,embedding in [(self.general,embedded[0:1]),(self.contextual,embedded[1:2])]:
                state=expert['features']
                lexical=transform_lexical(texts_for_features([row],state.get('input_format')=='genre-v1'),state)
                predictions.append(predict_heads(combine_features(embedding,lexical,state),expert['heads']))
            result=route_predictions(row.get('kind'),*predictions)
            return {'version':self.card['version'],'predictions':result,'needs_review':True,
                    'warning':'Прототип: AI/автоматическая разметка, score не откалиброван. Ответ требует проверки.'}
        state = self.payload["features"]
        genre_aware = state.get("input_format")=="genre-v1"
        with self.lock:
            embedded = self.encoder.encode(encoder_texts([row],state) if genre_aware else [model_text(row)],
                                           normalize_embeddings=True,show_progress_bar=False)
        lexical = transform_lexical(texts_for_features([row],genre_aware),state)
        result = predict_heads(combine_features(embedded,lexical,state),self.payload["heads"])
        return {"version":self.card["version"],"predictions":result,"needs_review":True,
                "warning":"Прототип: AI/автоматическая разметка, score не откалиброван. Ответ требует проверки."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model",type=Path,required=True)
    parser.add_argument("--cache",type=Path,required=True)
    parser.add_argument("--report",type=Path,required=True)
    parser.add_argument("--port",type=int,default=8012)
    args = parser.parse_args()
    model = LocalModel(args.model,args.cache)
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if report["new_version"] != model.card["version"]:
        raise ValueError("Comparison report does not match the served model")
    names = DEPT_NAMES|SENTIMENT_NAMES|TYPE_NAMES|{"local":"Павлодар","not_local":"Другой город / область","possible":"Место неясно"}
    page = (Path(__file__).parent/"local_lab.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def response(self,status,data,content_type="application/json; charset=utf-8"):
            raw = data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type",content_type)
            self.send_header("Content-Length",str(len(raw)))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("X-Frame-Options","DENY")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path=="/":
                self.response(200,page,"text/html; charset=utf-8")
            elif self.path=="/report.json":
                self.response(200,{"report":report,"names":names,"card":model.card})
            elif self.path=="/health":
                self.response(200,{"ok":True,"version":model.card["version"],"local_only":True})
            else:
                self.response(404,{"error":"Not found"})

        def do_POST(self):
            if self.path!="/predict":
                self.response(404,{"error":"Not found"});return
            origin = self.headers.get("Origin")
            if origin and origin not in (f"http://localhost:{args.port}",f"http://127.0.0.1:{args.port}"):
                self.response(403,{"error":"Origin rejected"});return
            if self.headers.get_content_type()!="application/json":
                self.response(415,{"error":"JSON required"});return
            try:
                length = int(self.headers.get("Content-Length","0"))
                if not 0<length<=40000:
                    raise ValueError("Некорректный размер сообщения")
                row = validate_input(json.loads(self.rfile.read(length)))
                self.response(200,model.predict(row))
            except (ValueError,TypeError,UnicodeError) as error:
                self.response(400,{"error":str(error)})
            except Exception:
                self.response(500,{"error":"Ошибка локального анализа"})

        def log_message(self,*args):
            pass  # Do not retain user input or browser activity.

    print(f"Model lab ready on http://127.0.0.1:{args.port}; {model.card['version']}",flush=True)
    ThreadingHTTPServer(("127.0.0.1",args.port),Handler).serve_forever()


if __name__=="__main__":
    main()
