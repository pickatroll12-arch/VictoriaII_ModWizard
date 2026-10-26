# minimal clausewitz reader (for verification only): returns list of (key, value) where value is str or list
import re
TOK=re.compile(r'"[^"]*"|[{}=]|[^\s{}="]+')
def parse(text):
    text=re.sub(r'#[^\n]*','',text)
    toks=TOK.findall(text); i=0
    def block():
        nonlocal i
        out=[]
        while i<len(toks):
            t=toks[i]
            if t=='}': i+=1; return out
            if i+1<len(toks) and toks[i+1]=='=':
                i+=2
                if toks[i]=='{': i+=1; v=block()
                else: v=toks[i].strip('"'); i+=1
                out.append((t,v))
            elif t=='{': i+=1; out.append((None,block()))
            else: out.append((None,t.strip('"'))); i+=1
        return out
    return block()
def read(path): return parse(open(path,encoding='latin-1').read())
