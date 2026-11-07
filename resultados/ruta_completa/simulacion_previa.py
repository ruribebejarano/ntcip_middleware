import sys,math,random,json
sys.path.insert(0,'.')
from servidor import rutas
from servidor.gestor_mision import GestorMision
from gateway.geometria import Interseccion, Acceso, rumbo_entre, desplazar
G=rutas.cargar_grafo()
O=(-12.074664,-77.082933);D=(-12.0649978,-77.0464372)
base=rutas.calcular_ruta(G,O,D); geo=base.geometria
C=[(-12.07481,-77.079598),(-12.075324,-77.077597),(-12.078797,-77.065448),(-12.080629,-77.058371),(-12.078604,-77.056702),(-12.075072,-77.053875),(-12.074103,-77.052998),(-12.072117,-77.051359),(-12.071142,-77.050556),(-12.06917,-77.048967),(-12.068197,-77.048128),(-12.067219,-77.047323),(-12.065324,-77.045697)]
def dist(a,b):return math.hypot((a[0]-b[0])*110574,(a[1]-b[1])*108900)
reg=[]
for k,c in enumerate(C):
    i=min(range(1,len(geo)),key=lambda j:dist((geo[j].lat,geo[j].lon),c))
    n=geo[i];p=geo[i-1];r=rumbo_entre(p.lat,p.lon,n.lat,n.lon)
    acc=[Acceso('R',round(r,1),1)]
    for off,lab,g in((180,'O',1),(90,'T1',2),(270,'T2',2)):acc.append(Acceso(lab,round((r+off)%360,1),g))
    reg.append(Interseccion(interseccion_id=f'R{k+1:02d}',rsu_id=str(101+k),lat=c[0],lon=c[1],accesos=tuple(acc)) if 'rsu_id' in Interseccion.__dataclass_fields__ else None)
print('campos',list(Interseccion.__dataclass_fields__))
def pos(s):
    for a,b in zip(geo,geo[1:]):
        if s<=b.distancia_acumulada_m:
            t=(s-a.distancia_acumulada_m)/max(b.distancia_acumulada_m-a.distancia_acumulada_m,1e-6)
            return a.lat+t*(b.lat-a.lat),a.lon+t*(b.lon-a.lon),rumbo_entre(a.lat,a.lon,b.lat,b.lon)
    a,b=geo[-2],geo[-1];return b.lat,b.lon,rumbo_entre(a.lat,a.lon,b.lat,b.lon)
def correr(perfil,sem,sigma=5.0):
    rnd=random.Random(sem);T=[0.0];ev=[]
    class L:
        def log(self,t,i,**e):ev.append((T[0],t,i,e))
    g=GestorMision(G,reg,enviar_m1=lambda r,b:None,enviar_m3=lambda r,b:None,enviar_mr=lambda o,b:None,enviar_me=lambda o,b:None,eventos=L(),ahora=lambda:T[0])
    final=(geo[-1].lat,geo[-1].lon)
    m=g.armar_mision('o',1,O,final)
    print(' paradas',[(p.rsu_id,p.acceso_id,round(p.distancia_llegada_m)) for p in m.ruta.paradas],'de',len(reg))
    s=0.0;seq=0;recorr=[]
    for v in perfil:
        la,lo,ru=pos(s)
        if v>0:
            la,lo=desplazar(la,lo,rnd.uniform(0,360),abs(rnd.gauss(0,sigma)))
        seq+=1;recorr.append((T[0],s))
        g.procesar_mp('o',la,lo,v*3.6,ru,seq=seq,fuente_velocidad='sintetica')
        s+=v;T[0]+=1
    return ev,recorr,m
def res(ev,recorr,m):
    by={}
    for t,ty,i,e in ev:
        if ty in('M1_tx','M3_tx'):by.setdefault(i,[]).append((t,ty,e))
    act=[]
    for i,l in sorted(by.items(),key=lambda kv:kv[1][0][0]):
        m1=[x for x in l if x[1]=='M1_tx'];m3=[x for x in l if x[1]=='M3_tx']
        t0=m1[0][0];s0=next(s for t,s in recorr if t>=t0)
        ip=i.split('-')[-1];d=m.paradas[ip].parada.distancia_llegada_m
        print('  ',ip,'dist',round(d),'M1 t=%d a %d m antes, eta_real %.0fs n_m1=%d'%(t0,d-s0,next((t for t,s in recorr if s>=d),recorr[-1][0])-t0,len(m1)),'M3',[(a[0],a[2].get('motivo')) for a in m3])
        act.append((t0,m3[-1][0] if m3 else recorr[-1][0]))
    mx=0
    for t,_ in recorr:mx=max(mx,sum(a<=t<b for a,b in act))
    print('  max simultaneas',mx,'fin',[(t,e) for t,ty,i,e in ev if ty=='mision_desarmada'],'recalculos',sum(ty=='ruta_recalculada' for _,ty,_,_ in ev))
L=base.longitud_total_m
print('A');ev,rc,m=correr([10.0]*int(L/10+3),3);res(ev,rc,m)
# B ilustrativo: 25 km/h->45 con 3 paradas
rnd=random.Random(7);perf=[];s=0;stops=sorted(rnd.uniform(300,L-200) for _ in range(3));v=9.0
while s<L+5:
    v=max(5.56,min(13.9,v+rnd.uniform(-1,1)))
    if stops and s>=stops[0]:
        perf+= [0.0]*rnd.randint(5,20);stops.pop(0)
    perf.append(v);s+=v
print('B',len(perf),'s');ev,rc,m=correr(perf,4);res(ev,rc,m)
print(' suspensiones',[(round(t),e.get('interseccion_id')) for t,ty,i,e in ev if ty=='solicitud_suspendida_detenido'])
