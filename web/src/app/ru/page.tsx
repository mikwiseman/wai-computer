import Link from "next/link";
import Image from "next/image";
import type { Metadata } from "next";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import styles from "../page.module.css";

const MAC_DMG_URL = "/releases/macos/WaiComputer-ru-latest.dmg";
const TESTFLIGHT_URL = "https://testflight.apple.com/join/rtnJQzwk";
const PRIVACY_URL = "/ru/privacy";

const CURRENT_YEAR = new Date().getFullYear();

export const metadata: Metadata = {
  title: "WaiComputer — AI-память для голоса",
  description:
    "Записывайте, расшифровывайте, ищите, спрашивайте Wai обо всём, что вы когда-либо говорили.",
  alternates: {
    canonical: "https://wai.computer/ru",
    languages: {
      en: "https://wai.computer",
      ru: "https://wai.computer/ru",
    },
  },
};

function MacIcon() {
  return (
    <svg
      className={styles.platformIcon}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M16.2 4.2c.7-.85 1.2-2 1-3.2-1 .05-2.2.7-2.95 1.5-.65.7-1.25 1.85-1.05 3 1.15.1 2.3-.55 3-1.3Zm2.5 8.05c-.05-2.65 2.15-3.9 2.25-3.95-1.2-1.8-3.1-2.05-3.8-2.1-1.6-.15-3.15.95-3.95.95-.8 0-2.05-.95-3.4-.9-1.75.05-3.35 1.05-4.25 2.65-1.8 3.15-.45 7.8 1.3 10.35.85 1.25 1.85 2.65 3.15 2.6 1.25-.05 1.75-.85 3.3-.85 1.55 0 2 .85 3.35.8 1.4-.05 2.25-1.25 3.1-2.5 1-1.45 1.4-2.85 1.4-2.95-.05-.05-2.7-1.05-2.75-4.1Z"
        fill="currentColor"
      />
    </svg>
  );
}

function IPhoneIcon() {
  return (
    <svg
      className={styles.platformIcon}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <rect
        x="6"
        y="2"
        width="12"
        height="20"
        rx="2.5"
        stroke="currentColor"
        strokeWidth="1.7"
        fill="none"
      />
      <line
        x1="10"
        y1="5"
        x2="14"
        y2="5"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
      <circle cx="12" cy="19" r="0.9" fill="currentColor" />
    </svg>
  );
}

function AndroidIcon() {
  return (
    <svg
      className={styles.platformIcon}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M4 19v-7a8 8 0 0 1 16 0v7H4Z"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinejoin="round"
        fill="none"
      />
      <circle cx="9" cy="14" r="0.9" fill="currentColor" />
      <circle cx="15" cy="14" r="0.9" fill="currentColor" />
      <line
        x1="6.5"
        y1="4.5"
        x2="8"
        y2="7"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
      <line
        x1="17.5"
        y1="4.5"
        x2="16"
        y2="7"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}

function WindowsIcon() {
  return (
    <svg
      className={styles.platformIcon}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <rect x="3" y="4" width="8.5" height="8.5" fill="currentColor" />
      <rect x="12.5" y="4" width="8.5" height="8.5" fill="currentColor" />
      <rect x="3" y="13.5" width="8.5" height="8.5" fill="currentColor" />
      <rect x="12.5" y="13.5" width="8.5" height="8.5" fill="currentColor" />
    </svg>
  );
}

function LinuxIcon() {
  return (
    <svg
      className={styles.platformIcon}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M12 2.2c-2.3 0-3.7 2.2-3.7 4.7 0 1.4.3 2.6.9 3.8-.5.7-1.8 2.4-2.6 4.3-.7 1.7-1.4 4.4-.7 5.8.4.8 1.2 1 2 1.1.7.1 1.4-.2 1.7-.6 1.2.6 2.7.8 4.4.4 1-.2 1.7-.6 2.3-.8.3.3 1 .5 1.7.4.8-.1 1.6-.4 2-1.1.7-1.3 0-4.1-.7-5.8-.8-1.9-2.1-3.6-2.6-4.3.6-1.2.9-2.4.9-3.8 0-2.5-1.3-4.7-3.6-4.7Z"
        stroke="currentColor"
        strokeWidth="1.5"
        fill="none"
      />
      <circle cx="10.3" cy="7.2" r="0.7" fill="currentColor" />
      <circle cx="13.7" cy="7.2" r="0.7" fill="currentColor" />
    </svg>
  );
}

function MicIcon() {
  return (
    <svg
      className={styles.featureIcon}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
    >
      <rect
        x="12"
        y="5"
        width="8"
        height="15"
        rx="4"
        stroke="currentColor"
        strokeWidth="1.8"
        fill="none"
      />
      <path
        d="M7 14a9 9 0 0 0 18 0"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        fill="none"
      />
      <line
        x1="16"
        y1="23"
        x2="16"
        y2="27"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg
      className={styles.featureIcon}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
    >
      <circle
        cx="14"
        cy="14"
        r="7"
        stroke="currentColor"
        strokeWidth="1.8"
        fill="none"
      />
      <line
        x1="19.5"
        y1="19.5"
        x2="25"
        y2="25"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

function BrainIcon() {
  return (
    <svg
      className={styles.featureIcon}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M11 7a4 4 0 0 0-4 4v1a3.5 3.5 0 0 0-1 6.5 4 4 0 0 0 5 3 4 4 0 0 0 5 0 4 4 0 0 0 5-3 3.5 3.5 0 0 0-1-6.5v-1a4 4 0 0 0-4-4 4 4 0 0 0-2.5.9A4 4 0 0 0 11 7Z"
        stroke="currentColor"
        strokeWidth="1.7"
        fill="none"
      />
      <line
        x1="16"
        y1="9"
        x2="16"
        y2="22"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
        strokeDasharray="2 2"
      />
    </svg>
  );
}

export default function RuHome() {
  return (
    <main className={styles.landing}>
      <header className={styles.nav}>
        <Link href="/ru" className={styles.brand} aria-label="WaiComputer">
          <span className={styles.brandMark} aria-hidden="true" />
          <span className={styles.brandWord}>WaiComputer</span>
        </Link>
        <nav className={styles.navLinks}>
          <Link href="/ru/pricing" className={styles.navLink}>
            Цены
          </Link>
          <Link href="/ru/benchmarks/dictation" className={styles.navLink}>
            Бенчмарк
          </Link>
          <LocaleSwitcher current="ru" />
          <Link href="/login" className={styles.signin}>
            Войти →
          </Link>
        </nav>
      </header>

      <section className={styles.hero}>
        <div className={styles.iconHalo}>
          <picture>
            <source
              srcSet="/app-icon-dark.png"
              media="(prefers-color-scheme: dark)"
            />
            <img
              className={styles.icon}
              src="/app-icon.png"
              width={160}
              height={160}
              alt=""
              fetchPriority="high"
            />
          </picture>
        </div>
        <h1 className={styles.headline}>
          AI-память для всего, что вы говорите.
        </h1>
        <p className={styles.subhead}>
          Запись на Mac или iPhone. Расшифровка в реальном времени. Поиск по
          всему, что вы говорили. Спросите Wai о чём угодно.
        </p>

        <div className={styles.downloads}>
          <a
            className={styles.downloadPrimary}
            href={MAC_DMG_URL}
            download
            data-testid="download-mac-ru"
          >
            <span className={styles.downloadTitle}>Скачать для Mac</span>
            <span className={styles.downloadMeta}>macOS 14+ · DMG</span>
          </a>
          <a
            className={styles.downloadGhost}
            href={TESTFLIGHT_URL}
            data-testid="download-ios-ru"
          >
            <span className={styles.downloadTitle}>iPhone</span>
            <span className={styles.downloadMeta}>TestFlight · бета</span>
          </a>
        </div>
      </section>

      <section className={styles.section} aria-labelledby="platforms-title">
        <header className={styles.sectionHeader}>
          <p className={styles.eyebrow}>Везде, где вы говорите</p>
          <h2 id="platforms-title" className={styles.sectionTitle}>
            Пять платформ. Одна память.
          </h2>
        </header>
        <ul className={styles.platformGrid} role="list">
          <li>
            <a
              className={`${styles.platformCard} ${styles.platformCardLive}`}
              href={MAC_DMG_URL}
              download
            >
              <MacIcon />
              <span className={styles.platformTitle}>Mac</span>
              <span className={`${styles.statusPill} ${styles.statusLive}`}>
                Доступно
              </span>
              <span className={styles.platformSubtitle}>
                Нативное приложение, подписанный DMG, macOS 14+.
              </span>
            </a>
          </li>
          <li>
            <a
              className={styles.platformCard}
              href={TESTFLIGHT_URL}
              target="_blank"
              rel="noopener noreferrer"
            >
              <IPhoneIcon />
              <span className={styles.platformTitle}>iPhone</span>
              <span className={`${styles.statusPill} ${styles.statusBeta}`}>
                Бета
              </span>
              <span className={styles.platformSubtitle}>
                Сборка через TestFlight, новая каждую неделю.
              </span>
            </a>
          </li>
          <li>
            <div className={styles.platformCardDisabled} aria-disabled="true">
              <AndroidIcon />
              <span className={styles.platformTitle}>Android</span>
              <span className={`${styles.statusPill} ${styles.statusSoon}`}>
                Скоро
              </span>
              <span className={styles.platformSubtitle}>
                На проверке в Play Store.
              </span>
            </div>
          </li>
          <li>
            <div className={styles.platformCardDisabled} aria-disabled="true">
              <WindowsIcon />
              <span className={styles.platformTitle}>Windows</span>
              <span className={`${styles.statusPill} ${styles.statusSoon}`}>
                Скоро
              </span>
              <span className={styles.platformSubtitle}>
                Сборка на WinUI 3 для Windows 10+.
              </span>
            </div>
          </li>
          <li>
            <div className={styles.platformCardDisabled} aria-disabled="true">
              <LinuxIcon />
              <span className={styles.platformTitle}>Linux</span>
              <span className={`${styles.statusPill} ${styles.statusSoon}`}>
                Скоро
              </span>
              <span className={styles.platformSubtitle}>
                AppImage для x86_64.
              </span>
            </div>
          </li>
        </ul>
      </section>

      <section className={styles.section} aria-labelledby="features-title">
        <header className={styles.sectionHeader}>
          <p className={styles.eyebrow}>Что умеет WaiComputer</p>
          <h2 id="features-title" className={styles.sectionTitle}>
            Запишите. Найдите. Спросите.
          </h2>
        </header>
        <ul className={styles.featureGrid} role="list">
          <li className={styles.featureCard}>
            <MicIcon />
            <h3 className={styles.featureTitle}>Записывайте любой момент</h3>
            <p className={styles.featureBody}>
              Mac, iPhone, голосовые заметки из вашей библиотеки. Расшифровка
              появляется по ходу разговора.
            </p>
          </li>
          <li className={styles.featureCard}>
            <SearchIcon />
            <h3 className={styles.featureTitle}>
              Ищите по всему, что вы сказали
            </h3>
            <p className={styles.featureBody}>
              Гибридный полнотекстовый и смысловой поиск по каждой расшифровке,
              которую вы когда-либо сохраняли.
            </p>
          </li>
          <li className={styles.featureCard}>
            <BrainIcon />
            <h3 className={styles.featureTitle}>Спрашивайте Wai о чём угодно</h3>
            <p className={styles.featureBody}>
              AI-память, которая помнит ваши слова и отвечает на ваши вопросы
              вашим же голосом.
            </p>
          </li>
        </ul>
      </section>

      <section className={styles.section} aria-labelledby="screens-title">
        <header className={styles.sectionHeader}>
          <p className={styles.eyebrow}>Как это выглядит</p>
          <h2 id="screens-title" className={styles.sectionTitle}>
            WaiComputer в браузере.
          </h2>
        </header>
        <div className={styles.screensStrip}>
          <figure className={styles.screenFrame}>
            <Image
              src="/screenshots/dashboard-library.png"
              alt="Библиотека WaiComputer в браузере"
              width={1400}
              height={875}
              sizes="(max-width: 960px) 100vw, 50vw"
            />
          </figure>
          <figure className={styles.screenFrame}>
            <Image
              src="/screenshots/recording-detail.png"
              alt="Расшифровка записи в WaiComputer"
              width={1400}
              height={875}
              sizes="(max-width: 960px) 100vw, 50vw"
            />
          </figure>
        </div>
        <p className={styles.screensCaption}>
          WaiComputer в браузере — Mac, iPhone и любой современный браузер.
        </p>
      </section>

      <section
        className={`${styles.section} ${styles.benchmarkTeaserSection}`}
        aria-labelledby="benchmark-teaser-title"
      >
        <div className={styles.benchmarkCard}>
          <p className={styles.benchmarkEyebrow}>Бенчмарк</p>
          <h2 id="benchmark-teaser-title" className={styles.benchmarkTitle}>
            Мы протестировали все ведущие модели диктовки. WaiComputer
            использует ту, что победила.
          </h2>
          <p className={styles.benchmarkBody}>
            Синтетические фикстуры и слепая арена в реальном времени по пяти
            провайдерам — мы замеряем WER, задержку и скорость финализации.
            Полный отчёт открыт.
          </p>
          <Link
            href="/ru/benchmarks/dictation"
            className={styles.benchmarkCta}
            data-testid="benchmark-cta"
          >
            Открыть бенчмарк →
          </Link>
        </div>
      </section>

      <section className={styles.section} aria-labelledby="pricing-teaser-title">
        <header className={styles.sectionHeader}>
          <p className={styles.eyebrow}>Цены</p>
          <h2 id="pricing-teaser-title" className={styles.sectionTitle}>
            Бесплатно для повседневных заметок. Pro — когда нужно везде.
          </h2>
        </header>
        <div className={styles.pricingTeaserGrid}>
          <article className={styles.pricingTeaserCard}>
            <h3 className={styles.pricingTeaserPlan}>Бесплатный</h3>
            <p className={styles.pricingTeaserPrice}>0 ₽</p>
            <ul className={styles.pricingTeaserBullets} role="list">
              <li>10 записей в неделю</li>
              <li>Расшифровка в реальном времени</li>
              <li>Поиск по библиотеке</li>
            </ul>
          </article>
          <article
            className={`${styles.pricingTeaserCard} ${styles.pricingTeaserCardPro}`}
          >
            <h3 className={styles.pricingTeaserPlan}>Pro</h3>
            <p className={styles.pricingTeaserPrice}>
              1290 ₽<span className={styles.pricingTeaserUnit}>/мес</span>
            </p>
            <ul className={styles.pricingTeaserBullets} role="list">
              <li>Без лимита на записи</li>
              <li>Спрашивайте Wai по всей памяти</li>
              <li>Приоритетные модели расшифровки</li>
            </ul>
          </article>
        </div>
        <p className={styles.pricingTeaserLink}>
          <Link
            href="/ru/pricing"
            className={styles.textLink}
            data-testid="pricing-link"
          >
            Все цены →
          </Link>
        </p>
      </section>

      <section className={styles.section} aria-labelledby="faq-title">
        <header className={styles.sectionHeader}>
          <p className={styles.eyebrow}>Вопросы</p>
          <h2 id="faq-title" className={styles.sectionTitle}>
            Что чаще спрашивают.
          </h2>
        </header>
        <dl className={styles.faqList}>
          <div className={styles.faqItem}>
            <dt className={styles.faqQuestion}>Что WaiComputer записывает?</dt>
            <dd className={styles.faqAnswer}>
              Любое аудио, которое вы выбрали записать — встречи, звонки,
              голосовые заметки, мысли на прогулке. Mac пишет системный звук
              плюс микрофон, iPhone — звук вокруг. Также можно импортировать
              файлы из своей библиотеки.
            </dd>
          </div>
          <div className={styles.faqItem}>
            <dt className={styles.faqQuestion}>Записи конфиденциальны?</dt>
            <dd className={styles.faqAnswer}>
              Да. Записи шифруются при передаче и на сервере, хранятся только
              для вас, не используются для обучения моделей и не продаются.
              Удалите запись — она исчезает с наших серверов. Полная политика —
              на /ru/privacy.
            </dd>
          </div>
          <div className={styles.faqItem}>
            <dt className={styles.faqQuestion}>
              Какие модели используются для расшифровки?
            </dt>
            <dd className={styles.faqAnswer}>
              Мы тестируем все ведущие модели и берём победителя. Сегодня:
              Soniox v4 для realtime, ElevenLabs Scribe v2 и Deepgram Nova-3
              для пакетной обработки. Полный лидерборд —
              на /ru/benchmarks/dictation.
            </dd>
          </div>
          <div className={styles.faqItem}>
            <dt className={styles.faqQuestion}>Можно ли экспортировать данные?</dt>
            <dd className={styles.faqAnswer}>
              Да. Каждую запись можно выгрузить в Markdown уже сейчас; PDF и
              скачивание аудио — следующие на очереди. Поделённые заметки имеют
              публичную ссылку, которую вы контролируете.
            </dd>
          </div>
          <div className={styles.faqItem}>
            <dt className={styles.faqQuestion}>Работает ли офлайн?</dt>
            <dd className={styles.faqAnswer}>
              Запись работает офлайн на Mac и iPhone — аудио ставится в очередь
              локально и загружается, когда появляется сеть. Расшифровка и Ask
              Wai требуют подключения.
            </dd>
          </div>
        </dl>
      </section>

      <footer className={styles.footer}>
        <span>© {CURRENT_YEAR} WaiWai</span>
        <a href={PRIVACY_URL}>Конфиденциальность</a>
        <a href="/ru/terms">Условия</a>
      </footer>
    </main>
  );
}
