import os
from pdfminer.high_level import extract_text as pdf_extract
import docx2txt
from sentence_transformers import SentenceTransformer
import numpy as np
from numpy.linalg import norm

MODEL = None
def get_model():
    global MODEL
    if MODEL is None:
        MODEL = SentenceTransformer('all-MiniLM-L6-v2')
    return MODEL

def extract_text_from_file(path):
    ext = path.split('.')[-1].lower()
    if ext == 'pdf':
        try:
            return pdf_extract(path)
        except Exception:
            return ''
    elif ext in ('docx','doc'):
        try:
            return docx2txt.process(path) or ''
        except Exception:
            return ''
    else:
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception:
            return ''

def get_embedding(text):
    model = get_model()
    return model.encode(text, convert_to_numpy=True)

def cosine_similarity(a,b):
    if a is None or b is None: return 0.0
    if norm(a)==0 or norm(b)==0: return 0.0
    return float(np.dot(a,b)/(norm(a)*norm(b)))
