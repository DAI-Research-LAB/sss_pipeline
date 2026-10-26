# Fig. 2 - conceptual framework of the reference implementation.
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Circle
plt.rcParams['font.family'] = 'Arial'
BLUE, LBLUE, GREEN, SAND, GREY = '#00629B', '#dbe7f3', '#e8f1e4', '#f6ecd9', '#333333'
fig, ax = plt.subplots(figsize=(7.16, 3.6), dpi=300)
ax.set_xlim(0, 100); ax.set_ylim(0, 50); ax.axis('off')

stages = [
    ('Ingestion and\nMetadata', LBLUE, 'black',
     ['• Preflight check:', '   standard / repaired /', '   unsupported', '• Ping table and raw', '   channel arrays', '• Dataset (ISO 19115) and', '   SSS companion metadata'], 'Ingestion layer'),
    ('Segment\nOrganization', '#a9cbe8', 'black',
     ['• Acquisition-aware rules:', '   length, time gap,', '   jump, stall', '• Segment index as', '   GeoJSON features', '• Ping and time ranges,', '   parameters per segment'], 'Segment layer'),
    ('Product\nGeneration', GREEN, 'black',
     ['• Preview strip per', '   segment', '• Local stitched variants:', '   slant range none / flat', '   fusion RMS / mean /', '   max / distance', '• Parameters recorded'], 'Product layer'),
    ('Visualization', SAND, 'black',
     ['• Interactive map viewer', '• Trackline, segments,', '   previews, variants,', '   basemaps', '• Manifest check before', '   the viewer is written'], 'Access layer'),
]
w, gap, x0, y0, h = 21, 4.6, 1, 13.5, 33
for i, (title, fc, tc, lines, layer) in enumerate(stages):
    x = x0 + i * (w + gap)
    ax.add_patch(FancyBboxPatch((x, y0), w, h, boxstyle='round,pad=0.3,rounding_size=1.2', fc=fc, ec=GREY, lw=0.8))
    ax.add_patch(Circle((x + w / 2, y0 + h + 0.2), 1.6, fc='white', ec='black', lw=0.8, zorder=3))
    ax.text(x + w / 2, y0 + h + 0.2, str(i + 1), color='black', ha='center', va='center', fontsize=7, weight='bold', zorder=4)
    ax.text(x + w / 2, y0 + h - 2.6, title, ha='center', va='top', fontsize=7.6, weight='bold', color=tc, linespacing=1.1)
    ax.plot([x + 1, x + w - 1], [y0 + h - 9.6] * 2, color=tc, lw=0.5)
    ax.text(x + 1.3, y0 + h - 10.8, '\n'.join(lines), ha='left', va='top', fontsize=6.2, color=tc, linespacing=1.4)
    ax.plot([x + 1, x + w - 1], [y0 + 3.6] * 2, color=tc, lw=0.5)
    ax.text(x + w / 2, y0 + 1.6, layer, ha='center', va='center', fontsize=6.2, style='italic', color=tc)
    if i < 3:
        ax.annotate('', xy=(x + w + gap - 0.6, y0 + h / 2), xytext=(x + w + 0.6, y0 + h / 2),
                    arrowprops=dict(arrowstyle='-|>', lw=1.4, color=GREY))

# cross-cutting provenance band
ax.add_patch(FancyBboxPatch((1, 0.8), 98, 9.6, boxstyle='round,pad=0.3,rounding_size=1.2', fc='white', ec=BLUE, lw=0.9, ls='--'))
ax.text(50, 8.6, 'Provenance links and FAIR-oriented packaging (cross-cutting, Section III)',
        ha='center', va='center', fontsize=7, weight='bold', color='black')
items = ['Source checksum and\ningestion record', 'Ping → segment →\nraw-array links',
         'Product parameters\nand manifests', 'Persistent IDs and\nreusable packaging']
for i, t in enumerate(items):
    ax.text(13.3 + i * 24.3, 4.0, t, ha='center', va='center', fontsize=6, linespacing=1.25)
    if i: ax.plot([1.3 + i * 24.3, 1.3 + i * 24.3], [1.8, 6.4], color=BLUE, lw=0.5)
for i in range(4):
    x = x0 + i * (w + gap) + w / 2
    ax.annotate('', xy=(x, 10.6), xytext=(x, y0 - 0.4), arrowprops=dict(arrowstyle='<|-|>', lw=0.6, color=BLUE, mutation_scale=8))

for ext in ('png', 'svg', 'pdf'):
    fig.savefig(f'fig_concept.{ext}', bbox_inches='tight', dpi=300)
