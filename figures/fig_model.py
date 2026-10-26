import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
plt.rcParams['font.family']='Arial'
fig,ax=plt.subplots(figsize=(7.16,3.9),dpi=300); ax.set_xlim(0,100); ax.set_ylim(0,56); ax.axis('off')
C={'src':'#dbe7f3','core':'#a9cbe8','prod':'#e8f1e4','meta':'#f6ecd9'}
def box(x,y,w,h,title,lines,fc,tc='black'):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.4,rounding_size=1.2',fc=fc,ec='#333',lw=0.8))
    ax.text(x+w/2,y+h-2.2,title,ha='center',va='top',fontsize=7.5,weight='bold',color=tc)
    ax.text(x+1.2,y+h-6.3,'\n'.join(lines),ha='left',va='top',fontsize=5.6,color=tc,linespacing=1.35)
def arrow(x1,y1,x2,y2,label='',lx=0,ly=0):
    ax.annotate('',xy=(x2,y2),xytext=(x1,y1),arrowprops=dict(arrowstyle='-|>',lw=0.8,color='#333'))
    if label: ax.text((x1+x2)/2+lx,(y1+y2)/2+ly,label,fontsize=5.4,style='italic',ha='center',color='black',
                      bbox=dict(fc='white',ec='none',pad=0.4))
box(1,38,20,16,'Source file',['XTF file','SHA-256 checksum','header: channels, freq.','sonar / system name'],C['src'])
box(1,15,20,16,'Ingestion record',['pass mode: standard /','  repaired / unsupported','repair action','source unmodified flag'],C['src'])
box(28,38,20,16,'Ping',['ping_id, timestamp','lat/lon (NavUnits), utm_x/y','depth, altitude, attitude','slant range, channel stats'],C['src'])
box(28,15,20,16,'Raw array',['per-ping .npy','per-channel samples','linked by','raw_array_path'],C['src'])
box(55,26,22,22,'Segment',['segment_id','ping range (start, end)','time range','LineString geometry','segmentation params:','  length, time gap, jump,','  stall rules'],C['core'])
box(82,38,17,16,'Product',['type: preview /','  stitched variant','generation params:','  slant mode, fusion,','  pixel size, stride'],C['prod'])
box(82,15,17,16,'Metric record',['entropy, contrast','coverage, overlap','seam proxy','per product'],C['prod'])
box(55,2,22,13,'Metadata',['dataset: ISO 19115 record','extended: SSS companion XML','  ping / channel / lineage'],C['meta'])
arrow(21,46,28,46,'parsed',0,2.6)
arrow(11,38,11,31,'classified by')
arrow(38,38,38,31,'stores')
arrow(48,44,55,40,'grouped',0.2,-3.4)
arrow(77,42,82,45)
arrow(90.5,38,90.5,31,'evaluated by')
arrow(66,26,66,15,'summarized in')
ax.plot([11,11],[15,8.5],color='#333',lw=0.8)
arrow(11,8.5,55,8.5,'recorded in lineage',0,1.6)
ax.text(50,55.5,'Backward lineage: Product → Segment → Ping → Raw array → Source file (checksum)',ha='center',fontsize=6.2,color='black')
for ext in ('png','svg','pdf'): fig.savefig(f'fig_model.{ext}',bbox_inches='tight',dpi=300)
