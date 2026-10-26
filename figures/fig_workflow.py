# Fig. 3 - operational workflow of the reference implementation (stages, artefacts, data flow).
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Circle
plt.rcParams['font.family'] = 'Arial'
BLUE, LBLUE, GREEN, SAND, GREY, RED = '#00629B', '#dbe7f3', '#e8f1e4', '#f6ecd9', '#333333', '#b03a2e'
fig, ax = plt.subplots(figsize=(7.16, 3.7), dpi=300)
ax.set_xlim(0, 100); ax.set_ylim(0, 52); ax.axis('off')


def node(x, y, w, h, num, title, files, fc, tc='black'):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.3,rounding_size=1', fc=fc, ec=GREY, lw=0.8))
    ax.add_patch(Circle((x + 1.2, y + h + 0.1), 1.35, fc='white', ec='black', lw=0.8, zorder=3))
    ax.text(x + 1.2, y + h + 0.1, num, color='black', ha='center', va='center', fontsize=5.6, weight='bold', zorder=4)
    ax.text(x + w / 2, y + h - 1.4, title, ha='center', va='top', fontsize=6.6, weight='bold', color=tc, linespacing=1.1)
    ax.text(x + w / 2, y + 1.0, '\n'.join(files), ha='center', va='bottom', fontsize=4.5, color=tc,
            family='monospace', linespacing=1.3)


def arrow(p, q, color=GREY):
    ax.annotate('', xy=q, xytext=p, arrowprops=dict(arrowstyle='-|>', lw=0.8, color=color, shrinkA=0, shrinkB=0))


def label(x, y, t, mono=True, **kw):
    ax.text(x, y, t, fontsize=4.6, color='black', family='monospace' if mono else 'sans-serif', **kw)


# nodes (rows: top y=34-46, middle y=18-30, bottom y=1-15)
node(0.5, 18, 10, 12, '1', 'Raw XTF\ninput', ['*.xtf', 'SHA-256'], LBLUE)
node(13.5, 18, 12, 12, '2', 'Preflight\ncompatibility\ncheck', ['standard |', 'repaired'], LBLUE)
node(28.5, 18, 12.5, 12, '3', 'Ping-level\nparsing', ['pings.csv', 'raw_arrays/*.npy'], LBLUE)
ax.text(34.75, 16.6, 'NavUnits → lat/lon, UTM\nnadir end detected', ha='center', va='top', fontsize=4.8,
        style='italic', color='black')
node(46.5, 34, 14, 12, '4', 'Metadata\ngeneration', ['dataset_mgds.xml', 'sss_extended.xml'], SAND)
node(46.5, 18, 14, 12, '5', 'Segment\nindexing', ['sss_index.geojson'], '#a9cbe8')
node(67, 34, 15, 12, '6a', 'Preview\nstrips', ['*.png + manifest'], GREEN)
node(67, 1, 15, 14, '6b', 'Local stitched\nproducts',
     ['*.png + manifest', 'slant: none, flat', 'fusion: RMS, MEAN,', 'MAX, DISTANCE'], GREEN)
node(88.5, 18, 11, 12, '7', 'Interactive\nviewer', ['viewer.html'], SAND)

# data flow
arrow((10.5, 24), (13.5, 24))
arrow((25.5, 24), (28.5, 24))
arrow((34.75, 30), (46.5, 40))
label(38.6, 37.0, 'pings.csv', rotation=39, ha='center', va='center')
arrow((41, 24), (46.5, 24))
label(43.75, 25.4, 'pings', ha='center')
arrow((60.5, 28), (67, 38))
arrow((60.5, 20), (67, 10))
arrow((60.5, 24), (88.5, 24))
label(74.5, 25.2, 'sss_index.geojson', ha='center')
arrow((82, 40), (88.5, 29))
arrow((82, 8), (88.5, 19))
ax.text(94, 16.6, 'manifests checked\nbefore writing', ha='center', va='top', fontsize=4.8, style='italic', color='black')

# unsupported branch
arrow((19.5, 18), (19.5, 12), color=RED)
ax.text(19.5, 10.8, 'unsupported:\nstop, no products', ha='center', va='top', fontsize=5, color='black')

# lineage band
ax.annotate('', xy=(1, 50), xytext=(99, 50), arrowprops=dict(arrowstyle='-|>', lw=0.9, color=BLUE, ls='--'))
ax.text(50, 50.9, 'Lineage recorded backward: product → manifest → segment → pings → raw arrays → source file',
        ha='center', va='bottom', fontsize=5.6, color='black')

for ext in ('png', 'svg', 'pdf'):
    fig.savefig(f'fig_workflow.{ext}', bbox_inches='tight', dpi=300)
