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
    fit: "Default all-rounder for dictation, realtime recording, and file transcription.",
    tags: ["dictation", "realtime", "file"],
  },
  {
    name: "Soniox v4",
    fit: "Best value candidate for multilingual realtime and long-form async transcription.",
    tags: ["dictation", "realtime", "file"],
  },
  {
    name: "Deepgram Flux",
    fit: "Turn-aware realtime model for dictation and agent-style short utterances.",
    tags: ["dictation", "realtime"],
  },
  {
    name: "Deepgram Nova-3",
    fit: "High-throughput long recording and file transcription model.",
    tags: ["recording", "file"],
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
  const top = results[0];

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
          <div>
            <p className={styles.eyebrow}>Speech benchmark</p>
            <h1>Dictation models, ranked by our own audio.</h1>
            <p className={styles.heroText}>
              Synthetic fixtures track repeatable accuracy and latency. The live arena lets
              signed-in testers dictate once and compare blind model outputs from the same audio.
            </p>
          </div>
          <div className={styles.scoreStrip} aria-label="Benchmark highlights">
            <div className={styles.scoreCell}>
              <span className={styles.scoreBar} style={{ height: "78px" }} />
              <span className={styles.scoreLabel}>
                <strong>{top ? pct(top.aggregate.wer) : "Pending"}</strong>
                WER leader
              </span>
            </div>
            <div className={styles.scoreCell}>
              <span className={styles.scoreBar} style={{ height: "102px" }} />
              <span className={styles.scoreLabel}>
                <strong>{top?.aggregate.speed_factor ?? "Pending"}</strong>
                Speed factor
              </span>
            </div>
            <div className={styles.scoreCell}>
              <span className={styles.scoreBar} style={{ height: "58px" }} />
              <span className={styles.scoreLabel}>
                <strong>{results.length || "Pending"}</strong>
                Models measured
              </span>
            </div>
          </div>
        </section>

        <section className={styles.leaderboard} aria-labelledby="leaderboard-title">
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

        <DictationBenchmarkArena />
      </div>
    </main>
  );
}
