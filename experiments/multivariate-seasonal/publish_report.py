"""Build the reviewable public research page and reproducibility download bundle."""
import hashlib,json,shutil
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from fields import ROOT,HERE
from model import SeasonalState

PUBLIC=Path('/home/ubuntu/climatetensor-xue/web/public')
DEST=PUBLIC/'research/multivariate-v1'

def main():
    r=json.loads((ROOT/'report.json').read_text())
    f=np.load(ROOT/'forecast.npz');m=np.load(ROOT/'model.npz')
    state=SeasonalState(m['climatology'],m['scale'])
    initial=state.encode(m['coefficients'][-1],11)
    replay=state.decode((initial@m['vectors'])@m['maps'],np.arange(6))
    np.testing.assert_allclose(replay,f['coefficients'],atol=1e-12,rtol=0)
    assert r['physical_variables']==16 and r['spectral_coefficients']==778
    assert np.nanmin(f['q850'])>0 and np.nanmin(f['q700'])>0
    assert all(np.isfinite(f[code]).any() for ch in r['channels'] for code in ch['fields'])
    qc={'saved_model_reproduces_forecast':True,'maximum_coefficient_replay_error':float(abs(replay-f['coefficients']).max()),
        'positive_humidity':True,'sst_below_source_floor_271_35_K':int(np.sum(f['sst']<271.35)),
        'sst_minimum_K':float(np.nanmin(f['sst'])),
        'sst_interpretation':'Unconstrained L6 reconstruction overshoots the ERSST lower bound; raw diagnostic output is not physically qualified. No silent clipping. SST is not an Xue map layer in this release.',
        'caution':'Delivery and numerical checks do not establish forecast skill or conservation.'}
    (ROOT/'quality-check.json').write_text(json.dumps(qc,indent=2)+'\n')
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(1,3,figsize=(14,4),layout='constrained')
    colors={'joint':'#137d92','independent_channels':'#a34a23','independent_ar1':'#6751a4'}
    labels={'joint':'Joint EOF / ridge','independent_channels':'Independent channels','independent_ar1':'Independent AR(1)'}
    for ax,field in zip(axes[:2],['wind500','sst']):
        for key in colors:
            ax.plot(np.arange(1,7),100*np.array(r['metrics'][key][field]['resolved_skill_vs_climatology']),
                    marker='o',color=colors[key],label=labels[key])
        ax.axhline(0,color='#888',lw=.8);ax.set_title(field+' · resolved anomaly MSE skill')
        ax.set_xlabel('Lead (months)');ax.set_ylabel('Improvement vs seasonal climate (%)');ax.grid(alpha=.15)
    base=np.array(r['normalized_total_coefficient_mse']['climatology'])
    for key in colors:
        axes[2].plot(np.arange(1,7),100*(1-np.array(r['normalized_total_coefficient_mse'][key])/base),
                     marker='o',color=colors[key],label=labels[key])
    axes[2].set_title('All 13 channels · normalized coefficient skill')
    axes[2].set_xlabel('Lead (months)');axes[2].grid(alpha=.15);axes[2].legend(fontsize=8)
    fig.suptitle('2020–2025 development backtest · fixed 1979–2014 fit / 2015–2019 selection')
    fig.savefig(ROOT/'skill.svg');fig.savefig(ROOT/'skill.png',dpi=150);plt.close(fig)
    norms=np.array(r['coupling']['block_frobenius_norms'])[0]
    fig,ax=plt.subplots(figsize=(8,7),layout='constrained')
    im=ax.imshow(norms,cmap='magma')
    names=r['coupling']['channel_order'];ax.set_xticks(range(13),names,rotation=60,ha='right');ax.set_yticks(range(13),names)
    ax.set_xlabel('Predicted channel');ax.set_ylabel('Initial channel')
    ax.set_title('Learned cross-variable coefficients · lead 1 month\nFrobenius norms in normalized coordinates; not causal effects')
    fig.colorbar(im,ax=ax);fig.savefig(ROOT/'coupling.svg');plt.close(fig)
    DEST.mkdir(parents=True,exist_ok=True)
    for name in ['forecast.npz','model.npz','backtest.npz','report.json','encoding-verification.json','quality-check.json','skill.svg','skill.png','coupling.svg']:
        shutil.copyfile(ROOT/name,DEST/name)
    for name in ['fields.py','fetch.py','project.py','model.py','train.py','test_model.py','contract.json','publish_report.py','README.md','requirements.txt']:
        shutil.copyfile(HERE/name,DEST/name)
    shutil.copyfile(HERE.parent/'typed-spectrum/spectrum.py',DEST/'spectrum.py')
    manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in DEST.iterdir() if p.is_file() and p.name!='sha256.json'}
    (DEST/'sha256.json').write_text(json.dumps(manifest,indent=2)+'\n')
    labels_zh={'t850':'850 hPa 温度','t2m':'2 m 温度','sst':'海温','sp':'地面气压','msl':'海平面气压',
        'z500':'500 hPa 位势','q850':'850 hPa 比湿（对数）','q700':'700 hPa 比湿（对数）',
        'w500':'500 hPa 垂直速度','w700':'700 hPa 垂直速度','wind850':'850 hPa 风','wind500':'500 hPa 风','wind250':'250 hPa 风'}
    rows=''.join('<tr><td>'+labels_zh[name]+'</td>'+''.join(f'<td>{100*r["metrics"][model][name]["resolved_skill_vs_climatology"][lead]:.2f}%</td>'
        for model,lead in [('joint',0),('independent_channels',0),('independent_ar1',0),('joint',5)])+'</tr>' for name in labels_zh)
    aggregate=r['normalized_total_coefficient_mse']
    total_skill=100*(1-np.mean(aggregate['joint'])/np.mean(aggregate['climatology']))
    worse=100*(np.mean(aggregate['joint'])/np.mean(aggregate['independent_channels'])-1)
    html='''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ClimateTensor · 多变量学习与检验</title><style>
body{margin:0;background:#0b1821;color:#e0eaf0;font:16px/1.85 system-ui,sans-serif}main{max-width:1060px;margin:40px auto;padding:0 22px 70px}a{color:#93ded0}h1{font-size:32px;line-height:1.4}h2{font-size:23px;margin-top:38px}.note{background:#19313d;border-left:3px solid #97d6bd;padding:15px 20px}.table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid #39505f;padding:8px;text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}.actions{display:flex;gap:20px;flex-wrap:wrap}img{width:100%;background:white;border-radius:5px}.muted{color:#abc0cd}li{margin:8px 0}code{font-size:13px}
</style><main><p>CLIMATETENSOR / EXPERIMENT 002</p><h1>把多种气象量连接到同一个球面谱状态</h1>
<p>16 个物理变量 · 13 个标量或向量通道 · 778 个系数 · 月平均 · 最高 6 阶</p>
<p class="note"><strong>已完成真实历史资料的联合训练、回测和预报重建。</strong><br>历史初始资料为 2025-12，目标为 2026-01—06 各月平均；生成于 2026-09-24。这不是实时天气预报，也不能用来判断某一次台风。未进行同化。</p>
<p class="actions"><a href="/?lang=zh&amp;model=ctmulti&amp;type=wind500">500 hPa 风 →</a><a href="/?lang=zh&amp;model=ctmulti&amp;type=tmp2m">2 m 温度 →</a><a href="/?lang=zh&amp;model=ctmulti&amp;type=spfh850">850 hPa 比湿 →</a><a href="/?lang=zh&amp;model=ctmulti&amp;type=prmsl">海平面气压 →</a><a href="/experiment.html">第一版风场对照</a></p>
<h2>第一轮结果</h2><p>联合模型相对季节气候态的整体归一化谱误差降低约 TOTAL_SKILL%，但比逐通道独立学习的误差高约 WORSE%。500 hPa 风一月改善约 6.60%，独立 AR(1) 为 9.05%。这次建立了可检验的多变量耦合，还没有证明联合学习总体更好。</p>
<p>拟合使用 1979—2014 年的 432 个月；2015—2019 年的 60 个月选择阶数和正则化强度，选中 32 个 EOF、惩罚 0.1。2020—2025 年为 72 个月的<strong>开发回测</strong>：其中 500 hPa 风的结果以前已经看过，不能再称为全新的独立留出检验。这轮没有用回测结果改选参数。</p>
<img src="/research/multivariate-v1/skill.svg" alt="联合模型、逐通道模型与 AR1 的六个月回测技巧曲线">
<div class="table"><table><thead><tr><th>通道</th><th>联合 · 1 月</th><th>独立通道 · 1 月</th><th>AR(1) · 1 月</th><th>联合 · 6 月</th></tr></thead><tbody>ROWS</tbody></table></div>
<p class="muted">表格为相对训练期月气候态的低阶谱 MSE 改善，负值表示更差。风的 U/V 合并评分；比湿为对数空间评分。完整观测域误差、比湿物理单位 RMSE 和全部提前量见报告。总体指标先用训练期尺度对每个通道归一化，再等权汇总；不是混加不同物理单位。未去除长期趋势，技巧可能包含趋势信息；没有证明逐年异常或局地天气的预测能力。</p>
<h2>学习器学了什么</h2><p>温度、海温、气压、位势、比湿和垂直速度使用标量球谐；850、500、250 hPa 的水平风分别使用成对的梯度与旋转向量球谐。保留奇偶阶和正余弦相位。每个变量先减去训练期拟合的年周期，再按通道的训练期异常幅度归一化；联合 EOF 提取共同变化，六组岭回归分别预测 1—6 个月后的状态。图中的非对角块就是实际拟合出的跨变量系数，它们是统计关系，不是因果证明。</p>
<img src="/research/multivariate-v1/coupling.svg" alt="十三个通道之间的一月统计预测系数块范数">
<p>独立通道对照使用相同数据、同一候选集合和验证期，每个通道单独选参。气候态、持续异常和独立 AR(1) 也被保留。这个原型尚未加入质量、能量守恒约束，也不是 Adva 原生学习器或 Floquet 动力系统。</p>
<h2>变量、掩膜和物理边界</h2><p>本轮训练：t850、t2m、sst、sp、msl、z500、q850、q700、u/v850、u/v500、u/v250、w500、w700。辐射、积雪、z1000 和相对湿度诊断尚未加入。大气资料为 NOAA PSL NCEP/NCAR R1，海温为 ERSST v5；并非之前的 ERA5 单时次样本扩展成了训练集。</p>
<p>海温只在有效海洋域拟合；气压层用地面气压作地下筛选；缺测不补零。比湿先取对数，重建后保持正值。海温的未约束低阶重建仍会超过原资料的低温下界（最低约 −4.95°C），这是已记录的表示缺陷；没有静默截断，本版海温不作为地图预报层发布。掩膜和低阶重建也不能保证全部物理约束。</p>
<p>地图提供 11 个图层、14 个物理分量；海温和地面气压保留在完整浮点下载中。全部图层的 6 帧均通过 Xue 原生解码和独立 Zarr 回读，无数值截断；域外值使用缺测码。网页量化会损失弱信号，例如风分量半步误差上限 0.5 m/s、垂直速度 0.025 Pa/s。浮点 NPZ 不受网页量化影响。</p>
<h2>逐步提高时空分辨率</h2><ol><li><strong>本轮：</strong>月平均、L6，先建立多变量和独立学习对照。</li><li><strong>下一步：</strong>保持月资料、划分和指标固定，仅把 L6 提高到 L12，检验新增空间模态是否有预测收益。</li><li><strong>随后：</strong>接入日资料，先比较日平均与周平均目标；重新确定反混叠聚合、训练窗口与验证协议。</li><li><strong>再提高到 L24：</strong>以误差、计算量和物理检查为依据，而不是只把地图画得更细。</li></ol><p>本轮没有提高时间或信息空间分辨率。显示网格为 2.5°，真实可表示尺度仍受 L6 限制；动画中间帧只是显示插值。</p>
<h2>下载与复现</h2><ul><li><a href="/research/multivariate-v1/forecast.npz" download>16 变量浮点预报 NPZ</a> · <a href="/research/multivariate-v1/model.npz" download>学习参数和历史谱系数</a> · <a href="/research/multivariate-v1/backtest.npz" download>所有基线与联合模型的回测谱系数</a></li>
<li><a href="/research/multivariate-v1/report.json">完整结果和数据来源</a> · <a href="/research/multivariate-v1/contract.json">训练前固定的实验约定</a> · <a href="/research/multivariate-v1/quality-check.json">物理与重放检查</a> · <a href="/research/multivariate-v1/encoding-verification.json">编码和 Zarr 回读</a></li>
<li><a href="/research/multivariate-v1/train.py" download>训练代码</a> · <a href="/research/multivariate-v1/model.py" download>学习器</a> · <a href="/research/multivariate-v1/project.py" download>谱投影</a> · <a href="/research/multivariate-v1/fetch.py" download>数据下载</a> · <a href="/research/multivariate-v1/test_model.py" download>科学检查</a> · <a href="/research/multivariate-v1/README.md">复现说明</a> · <a href="/research/multivariate-v1/requirements.txt">依赖版本</a> · <a href="/research/multivariate-v1/sha256.json">全部文件与 SHA-256</a></li><li><a href="/data/latest-ctmulti.json">MULTI 的 Xue 发布指针</a></li></ul>
<p>资料提供：<a href="https://psl.noaa.gov/data/gridded/data.ncep.reanalysis.html">NOAA PSL NCEP/NCAR R1</a>、<a href="https://psl.noaa.gov/data/gridded/data.noaa.ersst.v5.html">NOAA ERSST v5</a>。可视化和数据格式：<a href="https://github.com/ringsaturn/xue">Xue</a>；原项目许可和底图署名保留。科学拟合、检验和预报生成：ClimateTensor 数值原型。</p></main></html>'''
    html=html.replace('TOTAL_SKILL',f'{total_skill:.2f}').replace('WORSE',f'{worse:.2f}').replace('ROWS',rows)
    (PUBLIC/'multivariate.html').write_text(html)
    print(json.dumps({'quality':qc,'public_download_files':len(manifest),'aggregate_skill_percent':total_skill,'joint_error_increase_vs_independent_percent':worse},indent=2))

if __name__=='__main__':main()
