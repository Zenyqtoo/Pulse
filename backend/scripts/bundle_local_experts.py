"""Bundle already-trained general and genre experts; no evaluation labels are read."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--general',type=Path,required=True)
    parser.add_argument('--contextual',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output must be a new version directory')
    general,contextual = [json.loads((p/'heads.json').read_text(encoding='utf-8')) for p in (args.general,args.contextual)]
    if (general['encoder'],general['encoder_revision']) != (contextual['encoder'],contextual['encoder_revision']):
        raise ValueError('Experts must share an encoder revision')
    args.output.mkdir(parents=True)
    for directory,prefix in [(args.general,'general'),(args.contextual,'contextual')]:
        shutil.copyfile(directory/'heads.json',args.output/(prefix+'.json'))
        shutil.copyfile(directory/'model_card.json',args.output/(prefix+'_card.json'))
    manifest={'format':'cityalert-local-experts-v4','version':'cityalert-e5-routed-v4',
              'encoder':general['encoder'],'encoder_revision':general['encoder_revision'],
              'general_file':'general.json','contextual_file':'contextual.json',
              'routing':'department=general; geo=contextual; tone/type=contextual for known post/article else general'}
    card=json.loads((args.contextual/'model_card.json').read_text(encoding='utf-8'))
    card.update(version=manifest['version'],created_at=datetime.now(timezone.utc).isoformat(),
                adaptation='frozen e5 + trained lexical/semantic expert heads; observable genre routing',
                experts=[general['version'],contextual['version']],routing=manifest['routing'],
                development_note='Old diagnostics and AI-reviewed dev were used for design selection. Not an independent final test.')
    (args.output/'heads.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (args.output/'model_card.json').write_text(json.dumps(card,ensure_ascii=False,indent=2),encoding='utf-8')
    print(manifest['version'])


if __name__=='__main__':
    main()
