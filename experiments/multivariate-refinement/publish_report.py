"""Build a resolution comparison page, stable data catalog and source download."""
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,shutil,zipfile
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from fields import HERE,ROOT,COARSE

PUBLIC=Path('/home/ubuntu/climatetensor-xue/web/public')
DEST=PUBLIC/'research/multivariate-l12-v1'

def main():
    r=json.loads((ROOT/'report.json').read_text());old=json.loads((COARSE/'report.json').read_text())
    comp=r['cross_resolution_comparison'];qc=json.loads((ROOT/'quality-check.json').read_text())
    names=comp['per_channel']; leads=np.arange(1,7)
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(1,3,figsize=(15,4.8),layout='constrained')
    for degree,color in [(6,'#8c603b'),(12,'#137d92')]:
        axes[0].plot(leads,comp['aggregate']['joint'][f'L{degree}_normalized_full_mse'],color=color,marker='o',label=f'L{degree} joint')
        axes[0].plot(leads,comp['aggregate']['climatology'][f'L{degree}_normalized_full_mse'],color=color,linestyle='--',label=f'L{degree} climatology')
        axes[1].plot(leads,np.sqrt(names['wind500']['joint'][f'L{degree}_full_physical_mse']),color=color,marker='o',label=f'L{degree} joint')
    axes[0].set_title('Full native-grid error · same training normalization')
    axes[0].set_ylabel('Normalized physical MSE');axes[0].legend(fontsize=8)
    axes[1].set_title('500 hPa full native-grid wind error');axes[1].set_ylabel('Vector RMSE (m/s)');axes[1].legend()
    for ax in axes[:2]:ax.set_xlabel('Lead (months)');ax.grid(alpha=.15)
    gains=[100*(1-np.mean(names[n]['joint']['L12_full_physical_mse'])/np.mean(names[n]['joint']['L6_full_physical_mse'])) for n in names]
    axes[2].barh(list(names),gains,color='#137d92');axes[2].invert_yaxis();axes[2].set_xlabel('MSE reduction, L12 vs L6 (%)')
    axes[2].set_title('Full physical fields · all six leads');axes[2].grid(axis='x',alpha=.15)
    fig.suptitle('2020–2025 development backtest · spatial refinement only; monthly cadence unchanged')
    fig.savefig(ROOT/'resolution-skill.svg');fig.savefig(ROOT/'resolution-skill.png',dpi=150);plt.close(fig)
    DEST.mkdir(parents=True,exist_ok=True)
    for name in ['forecast.npz','forecast-on-coarse-grid.npz','model.npz','backtest.npz','report.json',
                 'quality-check.json','encoding-verification.json','coarse-preservation-before.json',
                 'resolution-skill.svg','resolution-skill.png']:
        shutil.copyfile(ROOT/name,DEST/name)
    for p in HERE.iterdir():
        if p.suffix in ['.py','.json','.md','.txt']:shutil.copyfile(p,DEST/p.name)
    study=HERE.parents[1]
    with zipfile.ZipFile(DEST/'source.zip','w',zipfile.ZIP_DEFLATED) as z:
        for folder in [HERE,HERE.parent/'multivariate-seasonal',HERE.parent/'typed-spectrum']:
            for p in folder.iterdir():
                if p.suffix in ['.py','.json','.md','.txt']:z.write(p,p.relative_to(study))
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in DEST.iterdir() if p.is_file() and p.name!='sha256.json'}
    (DEST/'sha256.json').write_text(json.dumps(hashes,indent=2)+'\n')
    original=json.loads((ROOT/'coarse-preservation-before.json').read_text())
    assert all(hashlib.sha256((PUBLIC/name).read_bytes()).hexdigest()==sha for name,sha in original.items())
    catalog={'schema_version':1,'updated_utc':datetime.now(timezone.utc).isoformat(),
        'time_statistic':'calendar month mean','initial_month':'2025-12','target_months':r['target_months'],
        'npz_schema':{'field_axes':['month','latitude','longitude'],'coordinates':['months','lat','lon'],
            'missing_value':'NaN','field_units':{code:ch['units'] for ch in r['channels'] for code in ch['fields']}},
        'historical_origin':True,'models':[],
        'samples':[{'id':'L12-on-coarse-grid','parent_model':'ctmulti12','spectral_degree':12,
                    'grid_step_degrees':2.5,'grid_shape':[71,144],
                    'forecast':'/research/multivariate-l12-v1/forecast-on-coarse-grid.npz',
                    'sha256':hashes['forecast-on-coarse-grid.npz'],
                    'meaning':'Exact grid subset of L12, not the original trained L6 model'}]}
    for degree,model,folder,shape,step in [(6,'ctmulti','multivariate-v1',[71,144],2.5),
                                          (12,'ctmulti12','multivariate-l12-v1',[141,288],1.25)]:
        prefix='/research/'+folder
        path=PUBLIC/f'research/{folder}/forecast.npz'
        catalog['models'].append({'id':model,'spectral_degree':degree,'grid_step_degrees':step,'grid_shape':shape,
            'coefficient_count':778 if degree==6 else 2698,'preserved_original':degree==6,
            'forecast':prefix+'/forecast.npz','parameters':prefix+'/model.npz','report':prefix+'/report.json',
            'forecast_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'latest_pointer':f'/data/latest-{model}.json','viewer':f'/?lang=zh&model={model}&type=wind500'})
    (PUBLIC/'research/resolutions.json').write_text(json.dumps(catalog,indent=2)+'\n')
    reduction=100*comp['aggregate']['joint']['mean_L12_improvement_vs_L6']
    season=100*comp['aggregate']['climatology']['mean_L12_improvement_vs_L6']
    six=comp['aggregate']['joint']['L6_normalized_full_mse'];twelve=comp['aggregate']['joint']['L12_normalized_full_mse']
    six_clim=comp['aggregate']['climatology']['L6_normalized_full_mse'];twelve_clim=comp['aggregate']['climatology']['L12_normalized_full_mse']
    own_skill6=100*(1-np.mean(six)/np.mean(six_clim));own_skill12=100*(1-np.mean(twelve)/np.mean(twelve_clim))
    labels={'t850':'850 hPa 温度','t2m':'2 m 温度','sst':'海温','sp':'地面气压','msl':'海平面气压',
        'z500':'500 hPa 位势','q850':'850 hPa 比湿','q700':'700 hPa 比湿','w500':'500 hPa 垂直速度',
        'w700':'700 hPa 垂直速度','wind850':'850 hPa 风','wind500':'500 hPa 风','wind250':'250 hPa 风'}
    rows=''.join(f'<tr><td>{labels[n]}</td><td>{100*names[n]["joint"]["L12_improvement_vs_L6"][0]:.2f}%</td><td>{g:.2f}%</td></tr>' for n,g in zip(names,gains))
    html=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ClimateTensor · 粗细两档谱预报</title><style>
body{{margin:0;background:#0b1821;color:#e0eaf0;font:16px/1.85 system-ui,sans-serif}}main{{max-width:1100px;margin:40px auto;padding:0 22px 70px}}a{{color:#93ded0}}h1{{font-size:32px;line-height:1.4}}h2{{font-size:23px;margin-top:36px}}.note{{background:#19313d;border-left:3px solid #97d6bd;padding:15px 20px}}.table{{overflow:auto}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{border-bottom:1px solid #39505f;padding:9px;text-align:right;white-space:nowrap}}th:first-child,td:first-child{{text-align:left}}.actions{{display:flex;gap:20px;flex-wrap:wrap}}img{{width:100%;background:white;border-radius:5px}}.muted{{color:#abc0cd}}li{{margin:8px 0}}code{{font-size:13px}}
</style><main><p>CLIMATETENSOR / SPATIAL REFINEMENT</p><h1>加密到 L12，L6 粗档仍可独立调用</h1>
<p class="note">两档都是真实训练后的实验预报。原始 L6 的数据、模型、发布指针及下载文件完整保留，没有用 L12 的降采样值替换。<br>仍为 <strong>2025-12 初始、2026-01—06 月平均</strong>的历史起报实验，生成于 2026-09-24；非实时、未同化。动画中间帧只作显示插值。</p>
<div class="actions"><a href="/?lang=zh&amp;model=ctmulti12&amp;type=wind500">细档 L12 →</a><a href="/?lang=zh&amp;model=ctmulti&amp;type=wind500">粗档 L6 →</a><a href="/multivariate.html">L6 原始检验页</a><a href="/experiment.html">早期单风场实验</a></div>
<h2>两档分别是什么</h2><div class="table"><table><thead><tr><th>版本</th><th>谱系数</th><th>显示网格</th><th>格点数</th><th>时间步</th></tr></thead><tbody><tr><td>L6 · 原始粗档</td><td>778</td><td>2.5°</td><td>71 × 144</td><td>月平均</td></tr><tr><td>L12 · 新细档</td><td>2,698</td><td>1.25°</td><td>141 × 288</td><td>月平均</td></tr></tbody></table></div>
<p>谱阶数翻倍，网格间距减半，时间分辨率保持不变。细网格包含原来的全部格点位置；显示网格更密不意味着已获得 1.25° 局地预报技巧。历史输入仍使用原始资料网格，没有把插值出来的点当作新增观测。</p>
<p>点开地图左上角的模型名称，可以在“细档 L12”和“粗档 L6”间切换。两档切换保留当前变量、月份、视角和播放状态，便于比较。原网址 <code>?model=ctmulti</code> 仍调用原始 L6；新版本用 <code>?model=ctmulti12</code>。</p>
<h2>在相同观测场上的检验</h2><p>训练仍为 1979—2014，验证为 2015—2019，2020—2025 为已经看过的开发回测。候选集合保持相同，L12 由验证期选中 64 个 EOF、惩罚 0.1。L6 的已发布模型不重新训练。</p>
<p>对原始观测域的总体归一化物理 MSE，L12 较 L6 降低 <strong>{reduction:.2f}%</strong>。同样比较季节气候态，其误差已降低 {season:.2f}%，说明很大一部分收益来自背景场表示更细。各自相对同分辨率气候态的总体改善为 L6 {own_skill6:.2f}%、L12 {own_skill12:.2f}%；这不是获得可靠局地或台风预报能力的证明。</p>
<img src="/research/multivariate-l12-v1/resolution-skill.svg" alt="L6和L12在相同完整观测域的误差、500hPa风误差和各变量改善">
<div class="table"><table><thead><tr><th>通道</th><th>一月 MSE 降幅</th><th>一至六月平均降幅</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="muted">比较对象为相同原生网格、相同有效域上的完整物理场，包含截断残差。比湿使用 kg/kg 的物理误差。汇总时，每个通道除以固定 L6 训练期气候态误差，再等权平均；没有直接比较维度不同的系数误差。独立通道、AR(1)、持续异常等对照完整保留在报告中。</p>
<h2>调用粗、细数据</h2><p><a href="/research/resolutions.json">统一数据目录 JSON</a> 列出每档的谱阶数、网格、时间、预报文件、学习参数、发布指针和 SHA-256，可供脚本或 Observable 读取。</p>
<ul><li><strong>原始粗档 L6：</strong><a href="/research/multivariate-v1/forecast.npz" download>16 变量浮点预报</a> · <a href="/research/multivariate-v1/model.npz" download>学习参数</a> · <a href="/data/latest-ctmulti.json">Xue 指针</a></li>
<li><strong>细档 L12：</strong><a href="/research/multivariate-l12-v1/forecast.npz" download>1.25° 浮点预报</a> · <a href="/research/multivariate-l12-v1/model.npz" download>学习参数</a> · <a href="/data/latest-ctmulti12.json">Xue 指针</a></li>
<li><strong>L12 模型在粗网格上的取样：</strong><a href="/research/multivariate-l12-v1/forecast-on-coarse-grid.npz" download>2.5° 浮点 NPZ</a>。这是同一 L12 模型在原格点的取值，不能当成原始 L6 预报。</li>
<li><a href="/research/multivariate-l12-v1/report.json">完整回测与来源</a> · <a href="/research/multivariate-l12-v1/backtest.npz" download>回测输出</a> · <a href="/research/multivariate-l12-v1/contract.json">训练前约定</a> · <a href="/research/multivariate-l12-v1/source.zip" download>复现代码包</a> · <a href="/research/multivariate-l12-v1/README.md">复现说明</a></li>
<li><a href="/research/multivariate-l12-v1/coarse-preservation-before.json">140 个粗档文件原始校验和</a> · <a href="/research/multivariate-l12-v1/quality-check.json">独立数值检查</a> · <a href="/research/multivariate-l12-v1/encoding-verification.json">编码与 Zarr 回读</a> · <a href="/research/multivariate-l12-v1/sha256.json">新版本文件校验和</a></li></ul>
<h2>保留的限制与下一步</h2><p>16 个训练变量保持不变，地图提供 11 个图层、14 个分量，海温和地面气压仍在完整下载中。海温低阶重建最低 {qc['sst_minimum_K']-273.15:.2f}°C，仍超过原资料低温下界，未通过物理边界检查，暂不作地图预报层。未施加能量或质量守恒，也没有原生 Adva 学习或同化。</p>
<p>细档温度编码扩展到 −80—47°C，仍保持 0.5°C 步长，使新增的南极低温细节完整保存；全部图层编码未截断，缺测域保持缺测。浮点 NPZ 保存网页量化前的输出。</p>
<p>相同观测域的投影矩阵只保存一份，从约 2.62 GiB 重复矩阵缩减到约 6.09 MiB；重放预报、掩膜一致性、投影残差不增和独立原网格风场评分都通过。后续再接日／周尺度，之后评估 L24；本轮只完成空间加密。</p>
<p>资料：<a href="https://psl.noaa.gov/data/gridded/data.ncep.reanalysis.html">NOAA PSL NCEP/NCAR R1</a>、<a href="https://psl.noaa.gov/data/gridded/data.noaa.ersst.v5.html">ERSST v5</a>。数据格式与地图：<a href="https://github.com/ringsaturn/xue">Xue</a>。学习、检验与预报生成：ClimateTensor 数值原型。</p></main></html>'''
    (PUBLIC/'resolution.html').write_text(html)
    print(json.dumps({'new_download_files':len(hashes),'coarse_objects_unchanged':len(original),
        'full_mse_improvement_percent':reduction,'climatology_improvement_percent':season,
        'same_resolution_climatology_skill_percent':{'L6':own_skill6,'L12':own_skill12}},indent=2))

if __name__=='__main__':main()
