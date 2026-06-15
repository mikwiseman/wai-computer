import Link from "next/link";
import Image from "next/image";
import type { Metadata } from "next";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { PaymentComplianceSection } from "./PaymentCompliance";
import styles from "../page.module.css";

const MAC_DMG_URL = "/releases/macos/WaiComputer-ru-latest.dmg";
const WEB_APP_URL = "/dashboard";
const TESTFLIGHT_URL = "https://testflight.apple.com/join/rtnJQzwk";
const PRIVACY_URL = "/ru/privacy";

const CURRENT_YEAR = new Date().getFullYear();

export const metadata: Metadata = {
  title: "WaiComputer — ИИ-память для голоса",
  description:
    "Сохраняйте выбранные встречи и голосовые заметки, расшифровывайте их, ищите и спрашивайте Wai.",
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

function WebIcon() {
  return (
    <svg
      className={styles.platformIcon}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeWidth="1.7"
        fill="none"
      />
      <path
        d="M3.5 12h17M12 3.5c2 2.2 3.1 5 3.1 8.5S14 18.3 12 20.5M12 3.5c-2 2.2-3.1 5-3.1 8.5S10 18.3 12 20.5"
        stroke="currentColor"
        strokeWidth="1.45"
        strokeLinecap="round"
        fill="none"
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
          Приватная ИИ-память для того, что вы сами записали.
        </h1>
        <p className={styles.subhead}>
          Запускайте запись на Mac, iPhone или в браузере только когда это
          нужно. Ищите по сохранённым расшифровкам и спрашивайте Wai о том, что
          вы записали.
        </p>

        <div className={`${styles.downloads} ${styles.downloadsWide}`}>
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
            href={WEB_APP_URL}
            data-testid="download-web-ru"
          >
            <span className={styles.downloadTitle}>Открыть Web</span>
            <span className={styles.downloadMeta}>Браузер · без установки</span>
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
          <p className={styles.eyebrow}>Там, где вы решили записать</p>
          <h2 id="platforms-title" className={styles.sectionTitle}>
            Три входа в одну память.
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
              className={`${styles.platformCard} ${styles.platformCardLive}`}
              href={WEB_APP_URL}
              data-testid="platform-web-ru"
            >
              <WebIcon />
              <span className={styles.platformTitle}>Web</span>
              <span className={`${styles.statusPill} ${styles.statusLive}`}>
                Доступно
              </span>
              <span className={styles.platformSubtitle}>
                Браузерная версия для записи, поиска, Ask Wai и настроек.
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
            <h3 className={styles.featureTitle}>Записывайте после нажатия старт</h3>
            <p className={styles.featureBody}>
              Mac, iPhone, браузер и импорт голосовых заметок из вашей
              библиотеки. Расшифровка идёт только во время активной записи.
            </p>
          </li>
          <li className={styles.featureCard}>
            <SearchIcon />
            <h3 className={styles.featureTitle}>
              Ищите по сохранённым расшифровкам
            </h3>
            <p className={styles.featureBody}>
              Полнотекстовый и смысловой поиск по записям и импортам, которые
              вы сохранили.
            </p>
          </li>
          <li className={styles.featureCard}>
            <BrainIcon />
            <h3 className={styles.featureTitle}>Спрашивайте Wai о чём угодно</h3>
            <p className={styles.featureBody}>
              ИИ-память, которая помнит сохранённые записи и отвечает на ваши
              вопросы по ним.
            </p>
          </li>
        </ul>
      </section>

      <section className={styles.section} aria-labelledby="screens-title">
        <header className={styles.sectionHeader}>
          <p className={styles.eyebrow}>Как это выглядит</p>
          <h2 id="screens-title" className={styles.sectionTitle}>
            WaiComputer в браузере
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
          Браузерная версия синхронизируется с Mac и iPhone.
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
            Синтетические тесты и слепая live-арена по пяти провайдерам: мы
            измеряем WER, задержку и скорость финализации.
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
            Бесплатно для повседневных голосовых заметок. Pro — когда
            WaiComputer нужен везде.
          </h2>
        </header>
        <div className={styles.pricingTeaserGrid}>
          <article className={styles.pricingTeaserCard}>
            <h3 className={styles.pricingTeaserPlan}>Бесплатный</h3>
            <p className={styles.pricingTeaserPrice}>0 ₽</p>
            <ul className={styles.pricingTeaserBullets} role="list">
              <li>3 000 слов в неделю</li>
              <li>Память с поиском за 30 дней</li>
              <li>ИИ-сводка к каждой записи</li>
            </ul>
          </article>
          <article
            className={`${styles.pricingTeaserCard} ${styles.pricingTeaserCardPro}`}
          >
            <h3 className={styles.pricingTeaserPlan}>Pro</h3>
            <p className={styles.pricingTeaserPrice}>
              999 ₽<span className={styles.pricingTeaserUnit}>/мес</span>
            </p>
            <ul className={styles.pricingTeaserBullets} role="list">
              <li>Без недельного лимита на слова</li>
              <li>Постоянная память с поиском</li>
              <li>Автоматизация Wai + доступ к MCP</li>
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

      <PaymentComplianceSection eyebrow="Оплата" title="Оплата и документы" />

      <section className={styles.section} aria-labelledby="faq-title">
        <header className={styles.sectionHeader}>
          <p className={styles.eyebrow}>Вопросы</p>
          <h2 id="faq-title" className={styles.sectionTitle}>
            Частые вопросы.
          </h2>
        </header>
        <dl className={styles.faqList}>
          <div className={styles.faqItem}>
            <dt className={styles.faqQuestion}>Что WaiComputer записывает?</dt>
            <dd className={styles.faqAnswer}>
              Только аудио, запись которого вы явно начали: встречи, звонки,
              голосовые заметки, мысли на прогулке. WaiComputer не слушает в
              фоне. Mac может записывать системный звук плюс микрофон во время
              активной записи; iPhone и Web используют микрофон.
            </dd>
          </div>
          <div className={styles.faqItem}>
            <dt className={styles.faqQuestion}>Записи конфиденциальны?</dt>
            <dd className={styles.faqAnswer}>
              Да. Записи шифруются при передаче и при хранении, доступны только
              вам, не используются для обучения моделей и не продаются. Удалите
              запись — она исчезнет с наших серверов. Полная политика — в
              разделе <Link href={PRIVACY_URL}>«Конфиденциальность»</Link>.
            </dd>
          </div>
          <div className={styles.faqItem}>
            <dt className={styles.faqQuestion}>
              Какие модели используются для расшифровки?
            </dt>
            <dd className={styles.faqAnswer}>
              Для живой диктовки и записи используется Deepgram Nova-3. Для
              полной расшифровки записи используется ElevenLabs Scribe v2.
              Текущая проверка стека —{" "}
              <Link href="/ru/benchmarks/dictation">в бенчмарке диктовки</Link>.
            </dd>
          </div>
          <div className={styles.faqItem}>
            <dt className={styles.faqQuestion}>Можно ли экспортировать данные?</dt>
            <dd className={styles.faqAnswer}>
              Да. Каждую запись можно выгрузить в Markdown уже сейчас; PDF и
              скачивание аудио — следующие на очереди. Заметки, которыми вы
              делитесь, получают публичную ссылку, которую вы контролируете.
            </dd>
          </div>
          <div className={styles.faqItem}>
            <dt className={styles.faqQuestion}>Работает ли офлайн?</dt>
            <dd className={styles.faqAnswer}>
              Запись работает офлайн на Mac и iPhone — аудио ставится в очередь
              локально и загружается, когда появляется сеть. Для расшифровки и
              Ask Wai нужно подключение.
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
