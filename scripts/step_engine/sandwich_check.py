import csv, sys, subprocess, os, statistics as st, tempfile
import pathlib
ROOT=pathlib.Path(__file__).resolve().parents[2]
SERQ=str(ROOT/'.serq/bin/serq')
PROG=str(pathlib.Path(__file__).with_name('prefill_only.sq'))
c_it=0.004; a=5.1527e-5; b=4.0196e-9; B=512
def load(d,n):
    return {int(r['session']):float(r['value']) for r in csv.DictReader(open(f'{d}/{n}.csv'))}
def run(lam, p_long, n_short, n_long, horizon=3000, seed=1):
    d=os.path.join(tempfile.mkdtemp(prefix='sandwich-'), f'd_{lam}_{p_long}_{n_short}_{n_long}')
    subprocess.run([SERQ,'run',PROG,'--dump',d,'--seed',str(seed),'--horizon',str(horizon),
        '--set',f'Lambda={lam}','--set',f'p_long={p_long}','--set',f'n_short={n_short}','--set',f'n_long={n_long}'],
        check=True,capture_output=True)
    A=load(d,'arr'); M=load(d,'size'); T=load(d,'ttft')
    ks=sorted(T, key=lambda k:(A[k],k))
    S=lambda m: a*m+b*m*m/2
    Sup=lambda m: S(m)+c_it*(1+m/B)
    delta=c_it+a*B+b*B*(n_long+B/2)
    Dlo=Dup=0; viol_lo=viol_up=0; maxgap_up=0; order_bad=0; prevD=-1
    tl=[];tu=[];te=[]
    for k in ks:
        Dlo=max(A[k],Dlo)+S(M[k]); Dup=max(A[k],Dup)+Sup(M[k])
        D=A[k]+T[k]
        if D < Dlo-1e-9: viol_lo+=1
        if D > Dup+delta+1e-9: viol_up+=1
        if D < prevD-1e-9: order_bad+=1
        prevD=max(prevD,D)
        tl.append(Dlo-A[k]); tu.append(Dup-A[k]); te.append(T[k])
    rho=lam*((1-p_long)*S(n_short)+p_long*S(n_long))
    print(f"lam={lam:5} p={p_long} n=({n_short},{n_long}) rho_lo={rho:.2f} N={len(ks)}  "
          f"TTFT lo/eng/up = {st.mean(tl):.4f} / {st.mean(te):.4f} / {st.mean(tu):.4f}  "
          f"viol lo={viol_lo} up={viol_up} out-of-order={order_bad}")
for args in [(10,0.2,64,2048),(20,0.2,64,2048),(25,0.2,64,2048),(100,0.0,64,64),(200,0.0,64,64),(300,0.0,64,64),(150,0.05,32,4096)]:
    run(*args)
