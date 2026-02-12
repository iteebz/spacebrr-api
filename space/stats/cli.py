import argparse
import json
from pathlib import Path

from space import stats
from space.lib import git
from space.lib.commands import echo, fail, space_cmd
from space.lib.display import stats as stats_display
from space.stats import retention


def render(
    hours: int = 24,
    rsi: str | None = None,
    commits: bool = False,
    days: int = 7,
    extension: bool = False,
    stability: bool = False,
    governance: bool = False,
    projects: bool = False,
    absence: bool = False,
    retention_flag: bool = False,
    project_id: str | None = None,
    export: str | None = None,
    json_output: bool = False,
) -> None:
    if export:
        public = stats.public_stats()
        Path(export).write_text(json.dumps(public, indent=2))
        echo(f"Exported to {export}")
        return

    if commits:
        data = stats.agent_commit_stats(days=days)
        if json_output:
            echo(json.dumps(data, indent=2))
            return
        total = data["total"]
        echo(
            f"[COMMIT ACTIVITY] ({days}d) {total['commits']} commits, +{total['added']}/-{total['removed']} lines"
        )
        for row in data["by_agent"]:
            echo(
                f"  {row['agent']}: {row['commits']} commits, +{row['added']}/-{row['removed']} ({row['net']:+d} net)"
            )
        return

    if extension:
        ext = stats.code_extension()
        if json_output:
            echo(json.dumps(ext, indent=2))
            return
        echo(f"[CODE EXTENSION] {ext['total']} agent-to-agent file extensions")
        for agent, data in sorted(ext["by_agent"].items(), key=lambda x: -x[1]["total"]):
            extends_str = ", ".join(
                f"{k}({v})" for k, v in sorted(data["extends"].items(), key=lambda x: -x[1])
            )
            echo(f"  {agent}: {data['total']} files - {extends_str}")
        return

    if rsi:
        commit_ts = git.get_commit_timestamp(rsi)
        if not commit_ts:
            fail(f"Commit not found: {rsi}")
        comparison = stats.rsi_comparison(commit_ts, hours)
        if json_output:
            echo(json.dumps(comparison, indent=2))
            return
        echo(f"[RSI COMPARISON] {rsi[:8]} @ {commit_ts}")
        echo(f"\n[BEFORE] ({hours}h)")
        for row in comparison["before"]["artifacts_per_spawn"]:
            echo(f"  {row['agent']}: {row['ratio']} artifacts/spawn ({row['spawns']} spawns)")
        comp_before = comparison["before"]["compounding"]
        echo(f"  compounding: {comp_before['rate']}%")
        echo(f"\n[AFTER] ({hours}h)")
        for row in comparison["after"]["artifacts_per_spawn"]:
            echo(f"  {row['agent']}: {row['ratio']} artifacts/spawn ({row['spawns']} spawns)")
        comp_after = comparison["after"]["compounding"]
        echo(f"  compounding: {comp_after['rate']}%")
        delta = comp_after["rate"] - comp_before["rate"]
        echo(f"\n[DELTA] compounding: {delta:+.1f}%")
        return

    if stability:
        stab = stats.commit_stability(days=days)
        if json_output:
            echo(json.dumps(stab, indent=2))
            return
        overall = stab["overall"]
        echo(
            f"[COMMIT STABILITY] ({days}d) {overall['fix_rate']}% correction rate ({overall['other_fixes']}/{overall['total']})"
        )
        echo("\n  Corrections = fixes by others (instability). Self-fixes = iterative refinement.")
        for row in stab["by_agent"]:
            self_fixes = row.get("self_fixes", 0)
            other_fixes = row.get("other_fixes", 0)
            echo(
                f"  {row['agent']}: {row['fix_rate']}% ({other_fixes} corrections, {self_fixes} refinements)"
            )
        return

    if governance:
        corrections = stats.cross_agent_corrections(days=days)
        reversal = stats.decision_reversal_rate()
        challenge = stats.decision_challenge_rate()
        half_life = stats.decision_half_life()
        influence = stats.decision_influence()
        precision = stats.decision_precision()
        decay = stats.knowledge_decay()
        if json_output:
            echo(
                json.dumps(
                    {
                        "corrections": corrections,
                        "reversal": reversal,
                        "challenge": challenge,
                        "half_life": half_life,
                        "influence": influence,
                        "precision": precision,
                        "knowledge_decay": decay,
                    },
                    indent=2,
                )
            )
            return
        if corrections.get("error"):
            echo(f"[CROSS-AGENT CORRECTIONS] {corrections['error']}")
        else:
            echo(
                f"[CROSS-AGENT CORRECTIONS] {corrections['rate']}% ({corrections['corrections']}/{corrections['total_fixes']})"
            )
            echo("  Adversarial oversight signal")
        echo(
            f"\n[DECISION CHALLENGE] {challenge['challenge_rate']}% received dissent ({challenge['challenged']}/{challenge['total_committed']})"
        )
        echo("  Governance metric from arxiv paper")
        echo(
            f"\n[DECISION REVERSAL] {reversal['reversal_rate']}% ({reversal['reversed']}/{reversal['total_committed']})"
        )
        echo("  Target: <5% (commitment stability)")
        if half_life["median_hours"] is not None:
            echo(
                f"\n[DECISION HALF-LIFE] {half_life['median_hours']}h median (p25={half_life['p25_hours']}h, p75={half_life['p75_hours']}h, n={half_life['sample_size']})"
            )
        else:
            echo("\n[DECISION HALF-LIFE] no data")
        echo(
            f"\n[DECISION INFLUENCE] {influence['influence_rate']}% referenced ({influence['referenced']}/{influence['total_decisions']})"
        )
        echo(
            f"\n[DECISION PRECISION] {precision['overall']['precision']}% accepted ({precision['overall']['actioned']}/{precision['overall']['actioned'] + precision['overall']['rejected']})"
        )
        if decay["buckets"]:
            echo(f"\n[KNOWLEDGE DECAY] ({decay['weeks']}w)")
            for b in decay["buckets"][:6]:
                bar = "#" * int(b["rate"] / 2) if b["rate"] > 0 else "."
                echo(f"  w{b['week']}: {b['rate']}% ({b['citations']}/{b['total']}) {bar}")
        return

    if projects:
        dist = stats.project_distribution(hours)
        if json_output:
            echo(json.dumps(dist, indent=2))
            return
        echo(f"[PROJECT DISTRIBUTION] ({hours}h, {dist['total']} spawns)")
        for row in dist["by_project"]:
            bar = "#" * int(row["share"] / 5) if row["share"] >= 5 else "."
            echo(
                f"  {row['project']}: {row['spawns']} ({row['share']}%, {row['agents']} agents) {bar}"
            )
        return

    if absence:
        data = stats.absence_metrics(hours * 7)
        if json_output:
            echo(json.dumps(data, indent=2))
            return
        window_days = data["hours"] // 24
        echo(f"[ABSENCE] ({window_days}d)")
        echo(f"  block duration: {data['block_duration_hours']}h avg (mention → response)")
        echo(f"  completion autonomy: {data['completion_autonomy']}%")
        echo(
            f"  input/output ratio: {data['input_output_ratio']} ({data['human_inputs']} human / {data['swarm_outputs']} swarm)"
        )
        echo(f"  tasks: {data['tasks_autonomous']}/{data['tasks_total']} completed autonomously")
        return

    if retention_flag:
        ret = retention.summary(project_id)
        if json_output:
            echo(json.dumps(ret, indent=2))
            return
        mr = ret["merge_rate"]
        echo(f"[RETENTION METRICS] {mr['days']}d")
        echo(f"  merge rate: {mr['rate']}% ({mr['merged_blind']}/{mr['opened']} PRs)")
        if ret["engagement"]:
            echo("\n[ENGAGEMENT]")
            for e in ret["engagement"][:10]:
                echo(f"  {e['project_name']}: {e['spawns_per_day']}/day ({e['spawns']} spawns)")
        if ret["compounding"]:
            c = ret["compounding"]
            if c["delta"] is not None:
                echo(f"\n[COMPOUNDING]")
                echo(f"  d{c['baseline_day']} score: {c['baseline_score']}")
                echo(f"  d{c['target_day']} score: {c['target_score']}")
                echo(f"  delta: {c['delta']:+.1f}")
            else:
                echo("\n[COMPOUNDING] insufficient data")
        return

    summary = stats.get_summary(hours)

    if json_output:
        echo(json.dumps(summary, indent=2))
        return

    echo(f"[PRODUCTIVITY] ({hours}h)")
    for row in summary["artifacts_per_spawn"]:
        echo(f"  {row['agent']}: {row['ratio']} artifacts/spawn ({row['spawns']} spawns)")

    loop = summary["loop_frequency"]
    if loop["max_consecutive"] > 2:
        echo(f"\n[LOOPS] max {loop['max_consecutive']} consecutive ({loop['agent']})")

    echo("\n[DECISIONS]")
    for status, count in summary["decision_flow"].items():
        echo(f"  {status}: {count}")

    echo(f"\n[QUESTIONS] {summary['open_questions']} open")

    if summary["engagement"]:
        echo(f"\n[ENGAGEMENT] ({hours}h)")
        for row in summary["engagement"]:
            ratio = row["ratio"] or 0
            echo(f"  {row['agent']}: {ratio} reply/insight ({row['insights']}i, {row['replies']}r)")

    comp = summary["compounding"]
    window_days = comp.get("window_hours", 168) // 24
    echo(
        f"\n[COMPOUNDING] ({window_days}d) {comp['rate']}% reference prior work ({comp['referencing']}/{comp['total']})"
    )
    if comp.get("by_agent"):
        for row in comp["by_agent"][:5]:
            if row["refs"] > 0:
                echo(f"  {row['agent']}: {row['rate']}% ({row['refs']}/{row['total']})")

    di = summary["decision_influence"]
    echo(
        f"\n[DECISION INFLUENCE] {di['influence_rate']}% decisions referenced ({di['referenced']}/{di['total_decisions']})"
    )
    if di["top"]:
        for prefix, count in di["top"][:3]:
            echo(f"  d/{prefix}: {count} refs")

    dp = summary["decision_precision"]
    echo(
        f"\n[DECISION PRECISION] {dp['overall']['precision']}% accepted ({dp['overall']['actioned']}/{dp['overall']['actioned'] + dp['overall']['rejected']})"
    )
    for row in dp["by_agent"]:
        if row["precision"] is not None:
            echo(f"  {row['agent']}: {row['precision']}% ({row['actioned']}a/{row['rejected']}r)")

    ts = summary["task_sovereignty"]
    window_days = ts.get("window_hours", 168) // 24
    echo(
        f"\n[SOVEREIGNTY] ({window_days}d) {ts['overall_rate']:.0f}% self-directed ({ts['self_created']}/{ts['total']})"
    )

    if summary.get("silent_agents"):
        echo(f"\n[SILENT] ({hours}h)")
        for row in summary["silent_agents"]:
            if row["hours_silent"]:
                echo(f"  {row['agent']}: {row['hours_silent']}h since activity")
            else:
                echo(f"  {row['agent']}: no recent activity")


def render_status(hours: int = 24, json_output: bool = False) -> None:
    data = stats.status(hours)

    if json_output:
        echo(json.dumps(data, indent=2))
        return

    echo(stats_display.format_status(data, hours))


def render_spawns(limit: int = 10, json_output: bool = False) -> None:
    data = stats.spawn_stats(limit)

    if json_output:
        echo(json.dumps(data, indent=2))
        return

    echo(stats_display.format_spawns(data, limit))


def render_swarm(json_output: bool = False) -> None:
    data = stats.swarm()

    if json_output:
        echo(json.dumps(data, indent=2))
        return

    echo(stats_display.format_swarm(data))


@space_cmd("stats")
def main() -> None:
    parser = argparse.ArgumentParser(prog="stats", description="Swarm productivity metrics")
    parser.add_argument("-h", "--hours", type=int, default=24, help="Time window in hours")
    parser.add_argument("--days", type=int, default=7, help="Time window in days")
    parser.add_argument("--rsi", help="Compare before/after RSI commit")
    parser.add_argument(
        "-c", "--commits", action="store_true", help="Show per-agent commit activity"
    )
    parser.add_argument("--extension", action="store_true", help="Show code extension metrics")
    parser.add_argument("--stability", action="store_true", help="Show commit fix rate")
    parser.add_argument("--governance", action="store_true", help="Show governance metrics")
    parser.add_argument("-p", "--projects", action="store_true", help="Show spawns per project")
    parser.add_argument("-a", "--absence", action="store_true", help="Show human absence metrics")
    parser.add_argument("-r", "--retention", action="store_true", help="Show retention metrics")
    parser.add_argument("--project-id", help="Filter retention by project")
    parser.add_argument("-s", "--spawns", type=int, help="Show last N spawns")
    parser.add_argument("--export", help="Export public stats to file")
    parser.add_argument("-o", "--overnight", action="store_true", help="Morning report format")
    parser.add_argument("-j", "--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if args.overnight:
        render_status(args.hours, json_output=args.json)
        return
    if args.spawns:
        render_spawns(args.spawns, json_output=args.json)
        return
    render(
        args.hours,
        args.rsi,
        args.commits,
        args.days,
        args.extension,
        args.stability,
        args.governance,
        args.projects,
        args.absence,
        args.retention,
        args.project_id,
        args.export,
        json_output=args.json,
    )
