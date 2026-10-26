import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
plt.rcParams['font.family']='Arial'
fig,ax=plt.subplots(figsize=(7.16,3.3),dpi=300); ax.set_xlim(0,100); ax.set_ylim(0,49); ax.axis('off')
def box(x,y,w,h,title,lines,fc,tc='black',fs=5.5):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.35,rounding_size=1',fc=fc,ec='#333',lw=0.7))
    ax.text(x+w/2,y+h-1.6,title,ha='center',va='top',fontsize=6.6,weight='bold',color=tc)
    ax.text(x+1,y+h-5.2,'\n'.join(lines),ha='left',va='top',fontsize=fs,color=tc,family='monospace',linespacing=1.3)
def arr(x1,y1,x2,y2,c='#333'):
    ax.annotate('',xy=(x2,y2),xytext=(x1,y1),arrowprops=dict(arrowstyle='-|>',lw=0.8,color=c))
box(0.5,14,20,20,'Source file',['NBP050501A.XTF','148,874,752 bytes','sha256:','EFF30615...D77C7D','ingestion: standard'],'#dbe7f3')
box(25,14,18,20,'Ping table',['pings.csv','17,104 rows','ping_id, timestamp,','lat, lon, depth, ...','raw_array_path'],'#dbe7f3')
box(25,0.5,18,10,'Raw arrays',['raw_arrays/*.npy','one file per ping'],'#dbe7f3')
box(48,8,20,31,'Segment',['id: seg_000014','pings: 2954-3130','n pings: 177','time: 05:10:24.00-','      05:11:12.75','length: 76.7 m','range: 199.8 m','segmentation:','  75 m / 10 s / 30 m'],'#a9cbe8')
prods=[('preview','strip, no fusion'),('rms_flat','flat, RMS'),('rms_none','none, RMS'),('mean_flat','flat, mean'),('distance_flat','flat, distance'),('max_flat','flat, max')]
for i,(n,p) in enumerate(prods):
    y=40-i*7.2
    ax.add_patch(FancyBboxPatch((74,y),25,5.4,boxstyle='round,pad=0.25,rounding_size=0.8',fc='#e8f1e4',ec='#333',lw=0.6))
    ax.text(75,y+2.7,f'{n}',fontsize=5.6,family='monospace',weight='bold',va='center')
    ax.text(98.5,y+2.7,p+('' if i==0 else ', 0.25 m'),fontsize=5,ha='right',va='center')
    arr(68,24,74,y+2.7,'#5a8f4e')
arr(20.5,24,25,24); arr(34,14,34,10.5); arr(43,24,48,24)
ax.text(45.5,25.6,'grouped',fontsize=5,style='italic',ha='center')
ax.text(22.7,25.6,'parsed',fontsize=5,style='italic',ha='center')
ax.text(86.5,47.6,'Forward: products derived from the same segment support',fontsize=5.8,ha='center',color='black')
ax.annotate('',xy=(1,40),xytext=(72,40),arrowprops=dict(arrowstyle='-|>',lw=1,color='#00629B',ls='--'))
ax.text(36,41.3,'Backward: product \u2192 segment \u2192 pings \u2192 raw arrays \u2192 source file (checksum)',fontsize=5.8,ha='center',color='black')
for ext in ('png','svg','pdf'): fig.savefig(f'fig_trace.{ext}',bbox_inches='tight',dpi=300)
