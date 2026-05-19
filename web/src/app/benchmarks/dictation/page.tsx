import Link from "next/link";
import type { Metadata } from "next";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { DictationBenchmarkArena } from "./DictationBenchmarkArena";
import benchmarkData from "../../../../public/benchmarks/dictation/latest.json";
import styles from "./benchmark.module.css";

type BenchmarkResult = {
  provider: string;
  model: string;
  label: string;
  description: string;
  aggregate: {
    wer: number;
    cer: number;
    latency_ms: number;
    speed_factor: number | null;
  };
};

const modelMatrix = [
  {
    name: "ElevenLabs Scribe v2",
    fit: "High-accuracy multilingual option for realtime recording and file transcription; slower dictation finalization.",
    tags: ["realtime", "file"],
  },
  {
    name: "Soniox v4",
    fit: "Default realtime dictation model after our startup eval: fast first text, explicit finalization, strong Russian fixture WER.",
    tags: ["dictation", "realtime", "file"],
  },
  {
    name: "Deepgram Nova-3",
    fit: "High-throughput full-transcript and file transcription model.",
    tags: ["file", "full transcript"],
  },
  {
    name: "Deepgram Flux",
    fit: "Fastest first-text candidate for live battles and short agent-style utterances.",
    tags: ["dictation", "realtime"],
  },
  {
    name: "Inworld STT-1",
    fit: "Realtime experiment path through Inworld’s STT stack; not a file model.",
    tags: ["dictation", "realtime"],
  },
];

export const metadata: Metadata = {
  title: "WaiComputer Dictation Benchmark",
  description: "Synthetic and live arena benchmark for WaiComputer dictation models.",
  alternates: {
    canonical: "https://wai.computer/benchmarks/dictation",
    languages: {
      en: "https://wai.computer/benchmarks/dictation",
      ru: "https://wai.computer/ru/benchmarks/dictation",
    },
  },
};

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export default function DictationBenchmarkPage() {
  const results = benchmarkData.results as BenchmarkResult[];
  const previewRows = results.slice(0, 3);

  return (
    <main className={styles.page}>
      <header className={styles.nav}>
        <Link href="/" className={styles.brand} aria-label="WaiComputer home">
          <span className={styles.brandMark} aria-hidden="true" />
          <span>WaiComputer</span>
        </Link>
        <nav className={styles.navLinks}>
          <Link href="/pricing">Pricing</Link>
          <LocaleSwitcher current="en" />
          <Link href="/login">Sign in</Link>
        </nav>
      </header>

      <div className={styles.shell}>
        <section className={styles.hero}>
          <div className={styles.heroCopy}>
            <h1>WaiComputer Dictation Arena</h1>
            <p className={styles.heroText}>
              Synthetic fixtures track repeatable accuracy and latency. The live arena lets
              testers dictate once, watch realtime models respond, then compare full transcripts
              from the same audio.
            </p>
            <div className={styles.heroActions}>
              <Link href="#arena">Start live battle</Link>
              <Link href="#leaderboard">View leaderboard</Link>
            </div>
          </div>
          <aside className={styles.arenaPreview} aria-label="Live dictation battle preview">
            <div className={styles.previewHeader}>
              <span>Blind model battle</span>
              <span className={styles.previewLive}>live</span>
            </div>
            <div className={styles.previewChart}>
              {previewRows.map((result, index) => (
                <div className={styles.previewRow} key={`${result.provider}-${result.model}`}>
                  <span className={styles.previewRank}>#{index + 1}</span>
                  <span className={styles.previewModel}>
                    <strong>{result.label}</strong>
                    <span>{result.provider} / {result.model}</span>
                  </span>
                  <span className={styles.previewMetric}>{pct(result.aggregate.wer)}</span>
                </div>
              ))}
            </div>
            <div className={styles.previewBattle} aria-hidden="true">
              {["A", "B", "C"].map((letter) => (
                <div className={styles.previewCard} key={letter}>
                  <span>{letter}</span>
                  <p>Model hidden until the tester votes.</p>
                </div>
              ))}
            </div>
          </aside>
        </section>

        <DictationBenchmarkArena />

        <section className={styles.leaderboard} id="leaderboard" aria-labelledby="leaderboard-title">
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>Leaderboard</p>
              <h2 id="leaderboard-title">{benchmarkData.suite}</h2>
            </div>
            <p>{benchmarkData.source}</p>
          </div>

          {results.length > 0 ? (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Rank</th>
                    <th>Model</th>
                    <th>WER</th>
                    <th>CER</th>
                    <th>Latency</th>
                    <th>Speed</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((result, index) => (
                    <tr key={`${result.provider}-${result.model}`}>
                      <td className={styles.rank}>#{index + 1}</td>
                      <td>
                        <span className={styles.modelName}>
                          <strong>{result.label}</strong>
                          <span>{result.provider} / {result.model}</span>
                        </span>
                      </td>
                      <td className={styles.metric}>{pct(result.aggregate.wer)}</td>
                      <td className={styles.metric}>{pct(result.aggregate.cer)}</td>
                      <td className={styles.metric}>{result.aggregate.latency_ms} ms</td>
                      <td className={styles.metric}>{result.aggregate.speed_factor}x</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className={styles.emptyState}>
              <span>No measured run is published yet.</span>
              <code>scripts/run-dictation-benchmark.py</code>
            </div>
          )}
        </section>

        <section className={styles.matrix} aria-labelledby="matrix-title">
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>Model fit</p>
              <h2 id="matrix-title">Which model belongs to which task</h2>
            </div>
          </div>
          <div className={styles.matrixGrid}>
            {modelMatrix.map((item) => (
              <article className={styles.matrixItem} key={item.name}>
                <div>
                  <h3>{item.name}</h3>
                  <p>{item.fit}</p>
                </div>
                <div className={styles.pills}>
                  {item.tags.map((tag) => (
                    <span className={styles.pill} key={tag}>{tag}</span>
                  ))}
                </div>
              </article>
            ))}
          </div>
        </section>

      </div>
    </main>
  );
}
