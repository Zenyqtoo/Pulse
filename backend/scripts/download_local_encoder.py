"""Explicit one-time public encoder download for the optional local model.

No API token or remote model code is required. The main application never runs
this script automatically. Use a dedicated ML virtual environment.
"""
import argparse
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',type=Path,required=True)
    args=parser.parse_args()
    from sentence_transformers import SentenceTransformer
    model=SentenceTransformer('intfloat/multilingual-e5-small',
        revision='614241f622f53c4eeff9890bdc4f31cfecc418b3',cache_folder=str(args.cache),
        trust_remote_code=False,device='cpu')
    print('Encoder cached. Further inference may run with HF_HUB_OFFLINE=1.')


if __name__=='__main__':
    main()
