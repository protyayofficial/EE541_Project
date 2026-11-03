"""Run: python run_experiments.py --slots 160 --backend lp"""
import argparse
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from src.scheduling import Config
from src.experiment import make_trace, run_policy, summarize

parser=argparse.ArgumentParser()
parser.add_argument('--slots',type=int,default=160)
parser.add_argument('--backend',choices=['lp','cvxpy'],default='lp')
parser.add_argument('--seed',type=int,default=7)
args=parser.parse_args()
results=Path(__file__).resolve().parent/'results';results.mkdir(exist_ok=True)
cfg=Config()
trace=make_trace(args.slots,args.seed)
policies=['fixed','greedy','channel','nominal','robust','adaptive']
df=pd.concat([run_policy(trace,policy,cfg,args.backend) for policy in policies],ignore_index=True)
df.to_csv(results/f'slots_{args.backend}.csv',index=False)
sumdf=summarize(df,cfg)
sumdf.to_csv(results/f'summary_{args.backend}.csv',index=False)
print(sumdf.to_string(index=False,float_format=lambda v:f'{v:.5f}'))
fig,ax=plt.subplots(figsize=(9,4))
for policy in policies:
    g=df[df['mode']==policy];ax.plot(g.t,g.b,label=policy,lw=1.2)
ax.set(xlabel='Time slot',ylabel='Queue occupancy (packet equivalents)',title='Synthetic trace: queue occupancy')
ax.legend(ncol=3,fontsize=8)
fig.tight_layout();fig.savefig(results/f'queue_{args.backend}.png',dpi=160);plt.close(fig)
fig,ax=plt.subplots(figsize=(8,4))
ax.bar(sumdf['mode'],sumdf['rejection_ratio'])
ax.set(ylabel='Rejected / arrived packet equivalents',title='Packet rejection ratio')
fig.tight_layout();fig.savefig(results/f'rejection_{args.backend}.png',dpi=160);plt.close(fig)
fig,ax=plt.subplots(figsize=(7,4))
for _,r in sumdf.iterrows():
    ax.scatter(r.energy_J,r.throughput_bps,label=r['mode'],s=55)
ax.set(xlabel='Total transmission energy (J)',ylabel='Mean throughput (bits/s)',title='Energy versus delivered throughput')
ax.legend(fontsize=8);fig.tight_layout();fig.savefig(results/f'energy_throughput_{args.backend}.png',dpi=160);plt.close(fig)
