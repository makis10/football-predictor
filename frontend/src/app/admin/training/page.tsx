import { redirect } from "next/navigation";
import { getSession, fetchWithAuth } from "@/lib/auth";
import { type NationalTrainingMetrics } from "@/lib/api";
import { getServerT } from "@/lib/i18n-server";

interface TrainingRun {
  id: number;
  run_at: string;
  model_version: string | null;

  n_train: number | null;
  n_cal: number | null;
  n_test: number | null;
  cal_cutoff: string | null;
  train_cutoff: string | null;
  test_cutoff: string | null;

  result_test_accuracy: number | null;
  result_home_recall: number | null;
  result_draw_recall: number | null;
  result_away_recall: number | null;
  result_home_precision: number | null;
  result_draw_precision: number | null;
  result_away_precision: number | null;

  goals_test_accuracy: number | null;
  goals_over_recall: number | null;
  goals_under_recall: number | null;
  goals_over_precision: number | null;

  draw_raw_mean: number | null;
  draw_cal_mean: number | null;
  draw_actual_rate: number | null;

  btts_test_accuracy: number | null;
  btts_gg_recall: number | null;
  btts_ng_recall: number | null;
  btts_gg_precision: number | null;
  btts_ng_precision: number | null;

  notes: string | null;
}

function pct(v: number | null) {
  if (v == null) return "—";
  return (v * 100).toFixed(1) + "%";
}

function num(v: number | null, decimals = 3) {
  if (v == null) return "—";
  return v.toFixed(decimals);
}

/**
 * Format a backend timestamp in Europe/Athens.
 *
 * This page is server-rendered, and the container runs in UTC — without an
 * explicit timeZone the times come out 3h behind (e.g. the 06:00 cron showed
 * as 03:00). Timezone-less strings (the national metrics.json `trained_at`)
 * are treated as UTC, since that's what the backend writes.
 */
function fmtAthens(iso: string): { date: string; time: string } {
  const hasTz = /[Zz]|[+-]\d{2}:?\d{2}$/.test(iso);
  const d = new Date(hasTz ? iso : iso + "Z");
  const tz = { timeZone: "Europe/Athens" } as const;
  return {
    date: d.toLocaleDateString("el-GR", { day: "2-digit", month: "2-digit", year: "numeric", ...tz }),
    time: d.toLocaleTimeString("el-GR", { hour: "2-digit", minute: "2-digit", hour12: false, ...tz }),
  };
}

function MetricCell({
  value,
  format = "pct",
  good,
  bad,
}: {
  value: number | null;
  format?: "pct" | "num";
  good?: number;
  bad?: number;
}) {
  const display = format === "pct" ? pct(value) : num(value);
  let color = "text-gray-300";
  if (value != null && good != null && bad != null) {
    if (good > bad) {
      color = value >= good ? "text-emerald-400" : value <= bad ? "text-red-400" : "text-yellow-400";
    } else {
      color = value <= good ? "text-emerald-400" : value >= bad ? "text-red-400" : "text-yellow-400";
    }
  }
  return <span className={color}>{display}</span>;
}

function RunCard({ run, isLatest }: { run: TrainingRun; isLatest: boolean }) {
  const { date: dateStr, time: timeStr } = fmtAthens(run.run_at);

  return (
    <div className={`rounded-xl border p-5 space-y-4 ${isLatest ? "border-blue-500 bg-blue-950/30" : "border-pitch-700 bg-pitch-900"}`}>
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <span className="text-white font-semibold">{dateStr}</span>
          <span className="text-gray-500 text-sm ml-2">{timeStr}</span>
          {isLatest && (
            <span className="ml-2 text-xs bg-blue-600 text-white px-2 py-0.5 rounded-full">latest</span>
          )}
        </div>
        <div className="text-xs text-gray-500">
          v{run.model_version ?? "—"}
          {run.train_cutoff && (
            <span className="ml-2">
              cutoff: train {run.cal_cutoff} / cal {run.train_cutoff} / test {run.test_cutoff}
            </span>
          )}
        </div>
      </div>

      {/* Data sizes */}
      <div className="grid grid-cols-3 gap-2 text-center">
        {[
          { label: "Train rows", value: run.n_train?.toLocaleString() ?? "—" },
          { label: "Cal rows",   value: run.n_cal?.toLocaleString() ?? "—" },
          { label: "Test rows",  value: run.n_test?.toLocaleString() ?? "—" },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-lg bg-pitch-800 p-3">
            <p className="text-xs text-gray-500">{label}</p>
            <p className="text-lg font-bold text-white">{value}</p>
          </div>
        ))}
      </div>

      {/* Result model */}
      <div>
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Result model (H/D/A)</p>
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-center">
            <thead>
              <tr className="text-gray-500 text-xs">
                <th className="pb-1 text-left"></th>
                <th className="pb-1">Accuracy</th>
                <th className="pb-1">Home recall</th>
                <th className="pb-1">Draw recall</th>
                <th className="pb-1">Away recall</th>
                <th className="pb-1">Home prec.</th>
                <th className="pb-1">Draw prec.</th>
                <th className="pb-1">Away prec.</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="text-left text-gray-400 text-xs pr-3">test set</td>
                <td><MetricCell value={run.result_test_accuracy} good={0.53} bad={0.47} /></td>
                <td><MetricCell value={run.result_home_recall}   good={0.65} bad={0.50} /></td>
                <td><MetricCell value={run.result_draw_recall}   good={0.30} bad={0.15} /></td>
                <td><MetricCell value={run.result_away_recall}   good={0.55} bad={0.40} /></td>
                <td><MetricCell value={run.result_home_precision} good={0.60} bad={0.48} /></td>
                <td><MetricCell value={run.result_draw_precision} good={0.40} bad={0.25} /></td>
                <td><MetricCell value={run.result_away_precision} good={0.55} bad={0.42} /></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Goals model */}
      <div>
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Goals model (O/U 2.5)</p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center text-sm">
          {[
            { label: "Accuracy",      v: run.goals_test_accuracy,  good: 0.58, bad: 0.52 },
            { label: "Over recall",   v: run.goals_over_recall,    good: 0.65, bad: 0.50 },
            { label: "Under recall",  v: run.goals_under_recall,   good: 0.60, bad: 0.45 },
            { label: "Over prec.",    v: run.goals_over_precision, good: 0.62, bad: 0.50 },
          ].map(({ label, v, good, bad }) => (
            <div key={label} className="rounded-lg bg-pitch-800 p-2">
              <p className="text-xs text-gray-500 mb-1">{label}</p>
              <MetricCell value={v} good={good} bad={bad} />
            </div>
          ))}
        </div>
      </div>

      {/* Draw calibration */}
      <div>
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Draw specialist calibration</p>
        <div className="grid grid-cols-3 gap-2 text-center text-sm">
          <div className="rounded-lg bg-pitch-800 p-2">
            <p className="text-xs text-gray-500 mb-1">Raw mean</p>
            <span className="text-gray-300">{num(run.draw_raw_mean)}</span>
          </div>
          <div className="rounded-lg bg-pitch-800 p-2">
            <p className="text-xs text-gray-500 mb-1">Calibrated mean</p>
            <MetricCell
              value={run.draw_cal_mean}
              format="num"
              good={run.draw_actual_rate != null ? run.draw_actual_rate + 0.01 : undefined}
              bad={run.draw_actual_rate != null ? run.draw_actual_rate - 0.01 : undefined}
            />
          </div>
          <div className="rounded-lg bg-pitch-800 p-2">
            <p className="text-xs text-gray-500 mb-1">Actual draw rate</p>
            <span className="text-gray-300">{num(run.draw_actual_rate)}</span>
          </div>
        </div>
        {run.draw_cal_mean != null && run.draw_actual_rate != null && (
          <p className={`text-xs mt-1 ${Math.abs(run.draw_cal_mean - run.draw_actual_rate) < 0.005 ? "text-emerald-400" : "text-yellow-400"}`}>
            {Math.abs(run.draw_cal_mean - run.draw_actual_rate) < 0.005
              ? "✓ Calibration ≈ actual draw rate"
              : `Δ = ${((run.draw_cal_mean - run.draw_actual_rate) * 100).toFixed(2)}pp vs actual`}
          </p>
        )}
      </div>

      {/* BTTS */}
      {run.btts_test_accuracy != null && (
        <div>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">BTTS / Goal-No Goal (Poisson)</p>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-center text-sm">
            {[
              { label: "Accuracy",    v: run.btts_test_accuracy, good: 0.62, bad: 0.55 },
              { label: "GG recall",   v: run.btts_gg_recall,     good: 0.65, bad: 0.50 },
              { label: "NG recall",   v: run.btts_ng_recall,     good: 0.60, bad: 0.45 },
              { label: "GG prec.",    v: run.btts_gg_precision,  good: 0.65, bad: 0.52 },
              { label: "NG prec.",    v: run.btts_ng_precision,  good: 0.60, bad: 0.48 },
            ].map(({ label, v, good, bad }) => (
              <div key={label} className="rounded-lg bg-pitch-800 p-2">
                <p className="text-xs text-gray-500 mb-1">{label}</p>
                <MetricCell value={v} good={good} bad={bad} />
              </div>
            ))}
          </div>
        </div>
      )}

      {run.notes && (
        <p className="text-xs text-gray-500 italic">{run.notes}</p>
      )}
    </div>
  );
}

function NationalMetricsCard({ m }: { m: NationalTrainingMetrics }) {
  if (!m.available) {
    return (
      <div className="rounded-xl border border-pitch-700 bg-pitch-900 p-6 text-center text-gray-500 text-sm">
        No metrics file found. Run{" "}
        <code className="font-mono text-gray-400">python scripts/train_national.py</code>{" "}
        to generate metrics.
      </div>
    );
  }

  const trained = m.trained_at ? fmtAthens(m.trained_at) : null;
  const trainedDateStr = trained?.date ?? "—";
  const trainedTimeStr = trained?.time ?? "";

  return (
    <div className="rounded-xl border border-emerald-800 bg-emerald-950/20 p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <span className="text-white font-semibold">{trainedDateStr}</span>
          <span className="text-gray-500 text-sm ml-2">{trainedTimeStr}</span>
          <span className="ml-2 text-xs bg-emerald-700 text-white px-2 py-0.5 rounded-full">national</span>
        </div>
        {m.test_start && (
          <div className="text-xs text-gray-500">test from {m.test_start}</div>
        )}
      </div>

      {/* Dataset sizes */}
      <div className="grid grid-cols-3 gap-2 text-center">
        {[
          { label: "Train rows", value: m.n_train?.toLocaleString() ?? "—" },
          { label: "Cal rows",   value: m.n_cal?.toLocaleString() ?? "—" },
          { label: "Test rows",  value: m.n_test?.toLocaleString() ?? "—" },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-lg bg-pitch-800 p-3">
            <p className="text-xs text-gray-500">{label}</p>
            <p className="text-lg font-bold text-white">{value}</p>
          </div>
        ))}
      </div>

      {/* Result model */}
      <div>
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Result model (H/D/A)</p>
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-center">
            <thead>
              <tr className="text-gray-500 text-xs">
                <th className="pb-1 text-left"></th>
                <th className="pb-1">Accuracy</th>
                <th className="pb-1">Home recall</th>
                <th className="pb-1">Draw recall</th>
                <th className="pb-1">Away recall</th>
                <th className="pb-1">Home prec.</th>
                <th className="pb-1">Draw prec.</th>
                <th className="pb-1">Away prec.</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="text-left text-gray-400 text-xs pr-3">test set</td>
                <td><MetricCell value={m.result_accuracy        ?? null} good={0.50} bad={0.44} /></td>
                <td><MetricCell value={m.result_home_recall     ?? null} good={0.65} bad={0.50} /></td>
                <td><MetricCell value={m.result_draw_recall     ?? null} good={0.25} bad={0.10} /></td>
                <td><MetricCell value={m.result_away_recall     ?? null} good={0.55} bad={0.40} /></td>
                <td><MetricCell value={m.result_home_precision  ?? null} good={0.58} bad={0.45} /></td>
                <td><MetricCell value={m.result_draw_precision  ?? null} good={0.38} bad={0.22} /></td>
                <td><MetricCell value={m.result_away_precision  ?? null} good={0.52} bad={0.40} /></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Goals model */}
      <div>
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Goals model (O/U 2.5)</p>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-center text-sm">
          {[
            { label: "Accuracy",     v: m.goals_accuracy    ?? null, good: 0.56, bad: 0.50 },
            { label: "Over recall",  v: m.goals_over_recall  ?? null, good: 0.65, bad: 0.50 },
            { label: "Under recall", v: m.goals_under_recall ?? null, good: 0.60, bad: 0.45 },
          ].map(({ label, v, good, bad }) => (
            <div key={label} className="rounded-lg bg-pitch-800 p-2">
              <p className="text-xs text-gray-500 mb-1">{label}</p>
              <MetricCell value={v} good={good} bad={bad} />
            </div>
          ))}
        </div>
      </div>

      {/* BTTS model */}
      <div>
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">BTTS model</p>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-center text-sm">
          {[
            { label: "Accuracy",  v: m.btts_accuracy  ?? null, good: 0.60, bad: 0.53 },
            { label: "GG recall", v: m.btts_gg_recall ?? null, good: 0.65, bad: 0.50 },
            { label: "NG recall", v: m.btts_ng_recall ?? null, good: 0.60, bad: 0.45 },
          ].map(({ label, v, good, bad }) => (
            <div key={label} className="rounded-lg bg-pitch-800 p-2">
              <p className="text-xs text-gray-500 mb-1">{label}</p>
              <MetricCell value={v} good={good} bad={bad} />
            </div>
          ))}
        </div>
      </div>

      {/* Draw calibration */}
      <div>
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Draw specialist calibration</p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center text-sm">
          <div className="rounded-lg bg-pitch-800 p-2">
            <p className="text-xs text-gray-500 mb-1">Raw mean</p>
            <span className="text-gray-300">{num(m.draw_raw_mean ?? null)}</span>
          </div>
          <div className="rounded-lg bg-pitch-800 p-2">
            <p className="text-xs text-gray-500 mb-1">Calibrated mean</p>
            <MetricCell
              value={m.draw_cal_mean ?? null}
              format="num"
              good={m.draw_actual_rate != null ? m.draw_actual_rate + 0.01 : undefined}
              bad={m.draw_actual_rate != null ? m.draw_actual_rate - 0.01 : undefined}
            />
          </div>
          <div className="rounded-lg bg-pitch-800 p-2">
            <p className="text-xs text-gray-500 mb-1">Actual draw rate</p>
            <span className="text-gray-300">{num(m.draw_actual_rate ?? null)}</span>
          </div>
          <div className="rounded-lg bg-pitch-800 p-2">
            <p className="text-xs text-gray-500 mb-1">Blend alpha</p>
            <span className="text-gray-300">{num(m.draw_blend_alpha ?? null)}</span>
          </div>
        </div>
        {m.draw_cal_mean != null && m.draw_actual_rate != null && (
          <p className={`text-xs mt-1 ${Math.abs(m.draw_cal_mean - m.draw_actual_rate) < 0.005 ? "text-emerald-400" : "text-yellow-400"}`}>
            {Math.abs(m.draw_cal_mean - m.draw_actual_rate) < 0.005
              ? "✓ Calibration ≈ actual draw rate"
              : `Δ = ${((m.draw_cal_mean - m.draw_actual_rate) * 100).toFixed(2)}pp vs actual`}
          </p>
        )}
      </div>
    </div>
  );
}

export default async function TrainingRunsPage() {
  const t = await getServerT();
  const session = await getSession();
  if (!(session?.user as any)?.isAdmin) redirect("/");

  const [runsRes, nationalRes] = await Promise.all([
    fetchWithAuth("/admin/training-runs"),
    fetchWithAuth("/national/training-metrics"),
  ]);
  const runs: TrainingRun[] = runsRes.ok ? await runsRes.json() : [];
  const nationalMetrics: NationalTrainingMetrics = nationalRes.ok
    ? await nationalRes.json()
    : { available: false };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Training History</h1>
        <p className="text-sm text-gray-500 mt-1">
          {t("adminTr.subtitle")}
        </p>
      </div>

      {/* National Team Model */}
      <section className="space-y-3">
        <div>
          <h2 className="text-lg font-semibold text-white">National Team Model</h2>
          <p className="text-xs text-gray-500">{t("adminTr.dailyRetrain")}</p>
        </div>
        <NationalMetricsCard m={nationalMetrics} />
      </section>

      {/* Club Model Training Runs */}
      <section className="space-y-3">
        <div>
          <h2 className="text-lg font-semibold text-white">Club Model Training Runs</h2>
          <p className="text-xs text-gray-500">{t("adminTr.weeklyRetrain")}</p>
        </div>
        {runs.length === 0 ? (
          <div className="rounded-xl border border-pitch-700 bg-pitch-900 p-8 text-center text-gray-500">
            {t("adminTr.noRuns")}
          </div>
        ) : (
          <div className="space-y-4">
            {runs.map((run, i) => (
              <RunCard key={run.id} run={run} isLatest={i === 0} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
