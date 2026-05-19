import Link from "next/link";
import type { Metadata } from "next";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { DictationBenchmarkArena } from "@/app/benchmarks/dictation/DictationBenchmarkArena";
import benchmarkData from "../../../../../public/benchmarks/dictation/latest.json";
import styles from "@/app/benchmarks/dictation/benchmark.module.css";

type BenchmarkResult = {
  provider: string;
  model: string;
  label: string;
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
    fit: "Дефолтная модель для диктовки, realtime-записи и распознавания файлов.",
    tags: ["диктовка", "realtime", "файл"],
  },
  {
    name: "Soniox v4",
    fit: "Сильный value-кандидат для multilingual realtime и длинной async-транскрибации.",
    tags: ["диктовка", "realtime", "файл"],
  },
  {
    name: "Deepgram Flux",
    fit: "Turn-aware realtime модель для коротких диктовок и voice-agent сценариев.",
    tags: ["диктовка", "realtime"],
  },
  {
    name: "Deepgram Nova-3",
    fit: "Быстрая модель для длинных записей и файловой транскрибации.",
    tags: ["запись", "файл"],
  },
  {
    name: "Inworld STT-1",
    fit: "Экспериментальный realtime путь через Inworld STT; не файловая модель.",
    tags: ["диктовка", "realtime"],
  },
];

const arenaCopy = {
  eyebrow: "Live arena",
  title: "Надиктуй один раз и сравни результаты вслепую",
  start: "Начать dictation battle",
  stop: "Остановить и сравнить",
  statuses: {
    idle: "Готово",
    recording: "Идёт запись",
    uploading: "Запускаем модели",
    done: "Выбери лучшую транскрипцию",
    error: "Нужно внимание",
  },
  signInMessage: "Войди, чтобы запустить приватный live benchmark.",
  signIn: "Войти",
  modelHidden: "Модель скрыта",
  selected: "Выбрано",
  pickWinner: "Выбрать",
  micUnavailable: "Запись с микрофона недоступна в этом браузере.",
  requestFailed: "Benchmark-запрос не удался.",
};

export const metadata: Metadata = {
  title: "WaiComputer Dictation Benchmark",
  description: "Синтетический и live arena benchmark моделей диктовки WaiComputer.",
  alternates: {
    canonical: "https://wai.computer/ru/benchmarks/dictation",
    languages: {
      en: "https://wai.computer/benchmarks/dictation",
      ru: "https://wai.computer/ru/benchmarks/dictation",
    },
  },
};

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export default function RuDictationBenchmarkPage() {
  const results = benchmarkData.results as BenchmarkResult[];
  const top = results[0];

  return (
    <main className={styles.page}>
      <header className={styles.nav}>
        <Link href="/ru" className={styles.brand} aria-label="WaiComputer">
          <span className={styles.brandMark} aria-hidden="true" />
          <span>WaiComputer</span>
        </Link>
        <nav className={styles.navLinks}>
          <Link href="/ru/pricing">Цены</Link>
          <LocaleSwitcher current="ru" />
          <Link href="/login">Войти</Link>
        </nav>
      </header>

      <div className={styles.shell}>
        <section className={styles.hero}>
          <div>
            <p className={styles.eyebrow}>Speech benchmark</p>
            <h1>Модели диктовки, ранжированные на нашем аудио.</h1>
            <p className={styles.heroText}>
              Синтетические фикстуры дают повторяемую проверку точности и latency.
              Live arena позволяет тестерам надиктовать один раз и выбрать лучший результат вслепую.
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
              <span>Измеренный прогон ещё не опубликован.</span>
              <code>scripts/run-dictation-benchmark.py</code>
            </div>
          )}
        </section>

        <section className={styles.matrix} aria-labelledby="matrix-title">
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>Model fit</p>
              <h2 id="matrix-title">Какая модель подходит для какой задачи</h2>
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

        <DictationBenchmarkArena copy={arenaCopy} signInHref="/login" />
      </div>
    </main>
  );
}
