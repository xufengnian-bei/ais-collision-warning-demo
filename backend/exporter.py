import csv
import io
import json
import zipfile
from datetime import datetime, timezone
from .algorithm import displacement

FIELDS = ["timestamp","own_mmsi","target_mmsi","actual_distance_m","dcpa_m","tcpa_s",
          "risk_dcpa","risk_tcpa","risk_distance","collision_risk","warning_by_risk",
          "warning_by_distance","predicted_warning","warning_reason","in_scope","data_quality",
          "sample_age_s","own_latitude","own_longitude","target_latitude","target_longitude",
          "own_sog","target_sog","own_held","target_held"]


def csv_bytes(rows, fields=FIELDS):
    out = io.StringIO()
    writer = csv.DictWriter(out,fieldnames=fields,extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8-sig")


def plot_png(engine):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.patches import Circle
    fig,(ax,chart)=plt.subplots(1,2,figsize=(14,6),layout="constrained")
    fig.suptitle(f"AIS encounter analysis | {engine.run_id}")
    rows = engine.rows
    if rows:
        own = {r["time"]:(r["own_latitude"],r["own_longitude"]) for r in rows}
        origin = next(iter(own.values()))
        def xy(lat,lon): return displacement(*origin,lat,lon)
        own_xy=[xy(*p) for p in own.values()]
        ax.plot(*zip(*own_xy),label=f"Own {engine.own_mmsi}",linewidth=2.2)
        ax.add_patch(Circle(own_xy[-1],engine.config.emergency_distance_m,color="orange",alpha=.12,label="Emergency distance"))
        for mmsi in sorted({r["target_mmsi"] for r in rows}):
            track = [r for r in rows if r["target_mmsi"]==mmsi]
            points = [xy(r["target_latitude"],r["target_longitude"]) for r in track]
            line, = ax.plot(*zip(*points),label=mmsi)
            chart.plot([r["time"]-engine.start_time for r in track],[r["collision_risk"] for r in track],label=mmsi,color=line.get_color())
            first=next((r for r in track if r["predicted_warning"]),None)
            if first:
                x,y=xy(first["target_latitude"],first["target_longitude"])
                ax.scatter([x],[y],marker="x",s=90,color="red",zorder=5)
                ax.annotate(f"First alert\nt+{first['time']-engine.start_time:.0f}s",(x,y),xytext=(8,8),textcoords="offset points",fontsize=8)
    ax.set(xlabel="East (m)",ylabel="North (m)",title="Observed tracks / first warning positions",aspect="equal")
    ax.grid(alpha=.2)
    ax.legend(fontsize=8)
    chart.axhline(engine.config.risk_threshold,color="red",linestyle="--",label=f"Threshold {engine.config.risk_threshold}")
    chart.set(xlabel="Elapsed simulation / replay time (s)",ylabel="Rule risk score",ylim=(-.03,1.05),title="Risk history (score, not probability)")
    chart.grid(alpha=.2)
    chart.legend(fontsize=8)
    out=io.BytesIO()
    fig.savefig(out,format="png",dpi=150)
    plt.close(fig)
    return out.getvalue()


def bundle(engine):
    out=io.BytesIO()
    report=engine.report()
    packets=engine.db.execute("SELECT raw FROM packets WHERE run_id=? AND direction='TX' ORDER BY rowid",(engine.run_id,)).fetchall()
    positions=[json.loads(r[0]) for r in engine.db.execute("SELECT data FROM positions WHERE run_id=? ORDER BY timestamp,mmsi",(engine.run_id,))]
    for p in positions: p["timestamp"]=p["timestamp_iso"]
    with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("evaluation.csv",csv_bytes(engine.rows))
        z.writestr("report.json",json.dumps(report,ensure_ascii=False,indent=2))
        if engine.scenario_id=="custom" and engine.source=="simulation":
            z.writestr("scene.json",json.dumps(engine.metadata()["scene_definition"],ensure_ascii=False,indent=2))
        z.writestr("tracks.png",plot_png(engine))
        z.writestr("transmitted.nmea","\r\n".join(p[0] for p in packets)+"\r\n")
        z.writestr("positions.csv",csv_bytes(positions,["mmsi","timestamp","latitude","longitude","sog","cog","ship_type","nav_status","name"]))
        z.writestr("说明.txt","本包来自 AIS 软件仿真或文件回放。report.json 记录数据来源和参数。\n"
                   "evaluation.csv 为逐秒风险，positions.csv 和 transmitted.nmea 可重新导入。\n"
                   "tracks.png 中红叉标记首次预警。complete=false 表示尚未回放完整时窗。\n"
                   "所有文件存储 UTC 时间，网页显示北京时间；速度单位为节，距离米、时间秒。\n"
                   "综合风险是规则得分，不是碰撞概率。最近会遇距离为有效数据的观测最小值。\n")
    return out.getvalue()
