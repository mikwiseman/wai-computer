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
    name: "Deepgram Nova-3",
    fit: "Единственный активный realtime speech-to-text путь для диктовки и живой записи.",
    tags: ["диктовка", "realtime"],
  },
  {
    name: "ElevenLabs Scribe v2",
    fit: "Единственная активная модель для полной файловой расшифровки записи.",
    tags: ["файл", "полный транскрипт"],
  },
];

const arenaCopy = {
  eyebrow: "File STT check",
  title: "Запиши один раз и проверь полную расшифровку",
  start: "Начать запись",
  stop: "Остановить и расшифровать",
  steps: {
    record: "Запись",
    run: "Расшифровка",
    vote: "Проверка",
  },
  statuses: {
    idle: "Готово",
    recording: "Идёт запись",
    uploading: "Расшифровываем",
    done: "Транскрипт готов",
    error: "Нужно внимание",
  },
  signInMessage: "Войди, чтобы запустить приватную проверку транскрибации.",
  signIn: "Войти",
  modelHidden: "Модель скрыта",
  selected: "Выбрано",
  savingVote: "Сохраняем",
  voteSaved: "Голос сохранён",
  pickWinner: "Подтвердить",
  newRound: "Новый раунд",
  recordingHint: "Говори естественно. Останови запись после полной фразы.",
  recordingLiveHint: "Говори естественно. Останови запись после полной фразы.",
  runningHint: "Тот же аудиофайл проходит через активную файловую STT-модель.",
  resultsHint: "Проверь транскрипт перед подтверждением.",
  privateRound: "Приватный раунд. Аудио используется только для этого запроса.",
  sameAudio: "Один аудиофайл.",
  blindVote: "Одна активная файловая STT-модель.",
  languageLabel: "Язык",
  runningModelsLabel: "Активная модель",
  outputsReadyLabel: "ответ готов",
  wordsLabel: "слов",
  languageOptions: [
    { label: "Авто", value: "multi" },
    { label: "EN", value: "en" },
    { label: "RU", value: "ru" },
  ],
  micUnavailable: "Запись с микрофона недоступна в этом браузере.",
  micPermissionDenied: "Доступ к микрофону заблокирован. Разреши микрофон в браузере и начни новый battle.",
  emptyRecording: "Аудио не записалось. Начни новый battle и говори хотя бы секунду.",
  requestFailed: "Запрос транскрибации не удался.",
  voteFailed: "Подтверждение не удалось сохранить.",
  transcribingSameAudio: "Распознаём тот же аудиофайл…",
  waitingForVote: "Ждём слепой выбор.",
  livePass: "Live pass",
  fullPass: "Full pass",
  liveWaiting: "Ждём live-транскрипт…",
  liveConnectionFailed: "Live benchmark не подключился. Попробуй новый раунд.",
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
  const previewRows = results.slice(0, 3);

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
          <div className={styles.heroCopy}>
            <h1>WaiComputer Арена диктовки</h1>
            <p className={styles.heroText}>
              Синтетические фикстуры дают повторяемую проверку точности и latency.
              Live arena позволяет надиктовать один раз, увидеть realtime-ответы моделей,
              а потом сравнить full-транскрипты на том же аудио.
            </p>
            <div className={styles.heroActions}>
              <Link href="#arena">Начать live battle</Link>
              <Link href="#leaderboard">Смотреть рейтинг</Link>
            </div>
          </div>
          <aside className={styles.arenaPreview} aria-label="Live dictation battle preview">
            <div className={styles.previewHeader}>
              <span>Слепое сравнение</span>
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
                  <p>Модель скрыта до выбора тестера.</p>
                </div>
              ))}
            </div>
          </aside>
        </section>

        <DictationBenchmarkArena copy={arenaCopy} signInHref="/login" />

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

      </div>
    </main>
  );
}
