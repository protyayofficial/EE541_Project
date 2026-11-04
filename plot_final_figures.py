"""Create concise final-project figures from saved evaluation outputs."""
import argparse
from pathlib import Path
import numpy as np,pandas as pd
from scipy.stats import t
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def main():
 p=argparse.ArgumentParser();p.add_argument('--root',default='results/final_evaluation');a=p.parse_args();root=Path(a.root);out=root/'figures';out.mkdir(parents=True,exist_ok=True)
 pairs=pd.read_csv(root/'solar/paired_vs_nominal.csv');methods=['fixed_margin','adaptive_harvest','adaptive_all']
 fig,axes=plt.subplots(1,3,figsize=(14,3.8),layout='constrained')
 for ax,(name,part) in zip(axes,pairs[(pairs.metric=='realized_cost')&(pairs.method.isin(methods))].groupby('dataset')):
  v=part.set_index('method').reindex(methods);y=np.arange(len(methods));err=np.vstack([v.delta-v.ci_low,v.ci_high-v.delta])
  ax.errorbar(v.delta,y,xerr=err,fmt='o',capsize=4);ax.axvline(0,color='black',linewidth=1);ax.set(yticks=y,yticklabels=methods,title=name,xlabel='Cost difference vs nominal');ax.grid(axis='x',alpha=.2)
 fig.suptitle('Solar-proxy windows: paired mean differences and approximate 95% intervals (n=10)');fig.savefig(out/'solar_paired_cost.png',dpi=200);plt.close(fig)
 raw=pd.read_csv(root/'sweep_normalized/per_seed.csv');metrics=['coverage_gain','coverage_arrival','coverage_harvest'];modes=['nominal','fixed_margin','adaptive_harvest','adaptive_all']
 per_seed=raw[raw['mode'].isin(modes)].groupby(['mode','seed'])[metrics].mean().reset_index();per_seed.to_csv(out/'coverage_per_seed.csv',index=False)
 fig,axes=plt.subplots(1,3,figsize=(12,4),sharey=True,layout='constrained')
 for ax,metric,label in zip(axes,metrics,['Channel lower bound','Arrival upper bound','Harvest lower bound']):
  stats=per_seed.groupby('mode')[metric].agg(['mean','std','count']).reindex(modes);err=t.ppf(.975,stats['count']-1)*stats['std']/np.sqrt(stats['count'])
  ax.bar(range(len(modes)),stats['mean'],yerr=err,capsize=3);ax.set(xticks=range(len(modes)),xticklabels=modes,ylim=(0,1),title=label,ylabel='Empirical one-step coverage');ax.tick_params(axis='x',rotation=45);ax.axhline(.8,linestyle='--',color='black',linewidth=1);ax.grid(axis='y',alpha=.2)
 fig.suptitle('Mean-normalized synthetic scenarios: coverage with approximate seed-level 95% intervals');fig.savefig(out/'one_step_coverage.png',dpi=200);plt.close(fig)
 print('Wrote figures to',out)
if __name__=='__main__':main()
