"""Run a complete scenario through real UDP and export results without a browser."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.engine import Engine
from backend.exporter import bundle, csv_bytes, plot_png
from backend.scenarios import SCENARIOS


async def run(args):
    output=Path(args.output_dir)
    output.mkdir(parents=True,exist_ok=True)
    engine=Engine(output/'cli-runs.db',args.udp_port,auto_stop_default=not args.no_auto_stop)
    await engine.start()
    try:
        engine.persist_report()
        engine.scenario_id=args.scenario
        await engine.reset(save_previous=False)
        for elapsed in range(1,engine.duration+1):
            await engine.tick(elapsed)
        engine.log_summary()
        report=engine.report()
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        (output/'evaluation.csv').write_bytes(csv_bytes(engine.rows))
        (output/'tracks.png').write_bytes(plot_png(engine))
        (output/'demo-results.zip').write_bytes(bundle(engine))
        print(f"场景：{SCENARIOS[args.scenario]['name']}")
        print(f"运行：{engine.run_id}，逐时刻评估：{len(engine.rows)}，预警事件：{len(engine.events)}")
        print(f"UDP 发送/接收：{engine.stats['sent']}/{engine.stats['received']}，解析错误：{engine.stats['errors']}")
        for target in report['targets']:
            first=target['first_warning']
            print(f"MMSI {target['target_mmsi']} | 首次预警 {first['timestamp'] if first else '无'} | "
                  f"峰值风险 {target['peak_risk']['collision_risk']:.4f} | "
                  f"观测最近距离 {target['closest_observed']['actual_distance_m']:.1f} m | "
                  f"提前量 {target['warning_lead_time_to_observed_closest_s']} s")
        print(f"结果包：{(output/'demo-results.zip').resolve()}")
    finally:
        await engine.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario',choices=list(SCENARIOS),default='mixed')
    parser.add_argument('--output-dir',default='artifacts/example')
    parser.add_argument('--udp-port',type=int,default=0,help='0 selects a free local port')
    parser.add_argument('--no-auto-stop',action='store_true',help='Run original constant-motion risk references without simulated stopping')
    asyncio.run(run(parser.parse_args()))
