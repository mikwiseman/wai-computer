import type { ReactNode } from "react";
import Image from "next/image";
import Link from "next/link";
import { CircleCheck } from "lucide-react";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { ThemeToggle } from "@/components/ThemeToggle";
import { MAC_DMG_URL, MAC_DMG_URL_RU } from "@/lib/links";
import styles from "@/app/page.module.css";

const TESTFLIGHT_URL = "https://testflight.apple.com/join/rtnJQzwk";
const CURRENT_YEAR = new Date().getFullYear();

type Locale = "en" | "ru";

interface LandingPageProps {
  locale: Locale;
  legal?: ReactNode;
}

const copy = {
  en: {
    home: "/",
    homeLabel: "WaiComputer home",
    product: "How it works",
    pricing: "Pricing",
    pricingHref: "/pricing",
    signIn: "Sign in",
    heroEyebrow: "The native WaiComputer app for Mac",
    heroTitle: "Build a second memory.",
    heroBody:
      "Record meetings, dictate into any app, and find what matters whenever you need it.",
    startFree: "Start free",
    downloadMac: "Download for Mac",
    web: "Open on the web",
    journeyEyebrow: "One continuous memory",
    journeyTitle: "From voice to answer.",
    steps: [
      { number: "01", title: "Said", body: "Record a meeting or dictate a thought." },
      { number: "02", title: "Understood", body: "Wai turns it into a summary and actions." },
      { number: "03", title: "Found", body: "Search or ask whenever you need the context." },
    ],
    productEyebrow: "Inside WaiComputer",
    productTitle: "Every memory, in one Inbox.",
    productBody:
      "Recording, dictation, summaries, search, and MCP live in one connected memory.",
    detailAlt: "WaiComputer recording summary and transcript",
    libraryAlt: "WaiComputer memory library",
    macEyebrow: "WaiComputer for macOS",
    macTitle: "Your memory starts on your Mac.",
    macBody:
      "Capture both sides of a meeting, dictate wherever you type, and keep every word in one searchable memory.",
    macMeta: "macOS 14 or later",
    alsoAvailable: "Also available",
    privacy: "Recording starts only when you tell it to.",
    platformWebTestId: "platform-web",
    platformMeta: {
      web: "Web",
      iphone: "iPhone beta",
    },
    finalTitle: "Keep what matters close.",
    finalBody: "Start free. Upgrade only when your memory needs to grow.",
    privacyLink: "Privacy",
    privacyHref: "/privacy",
    termsLink: "Terms",
    termsHref: "/terms",
    benchmarkLink: "Dictation benchmark",
    benchmarkHref: "/benchmarks/dictation",
  },
  ru: {
    home: "/ru",
    homeLabel: "WaiComputer",
    product: "Как работает",
    pricing: "Цены",
    pricingHref: "/ru/pricing",
    signIn: "Войти",
    heroEyebrow: "Приложение WaiComputer для Mac",
    heroTitle: "Не держите всё в голове.",
    heroBody:
      "Записывайте встречи, диктуйте текст в любом приложении и находите важное, когда оно понадобится.",
    startFree: "Попробовать бесплатно",
    downloadMac: "Скачать для Mac",
    web: "Открыть в браузере",
    journeyEyebrow: "Как работает WaiComputer",
    journeyTitle: "Запишите один раз. Найдите в любой момент.",
    steps: [
      { number: "01", title: "Запись", body: "Запишите встречу или надиктуйте мысль." },
      { number: "02", title: "Главное", body: "Получите расшифровку, краткий итог и список задач." },
      { number: "03", title: "Поиск", body: "Ищите по словам или задавайте вопросы по своим записям." },
    ],
    productEyebrow: "Всё в одном месте",
    productTitle: "Откройте запись и сразу увидите главное.",
    productBody:
      "Запись, расшифровка, краткий итог и задачи собраны в одном окне. Все записи находятся в общей библиотеке.",
    detailAlt: "Краткий итог и расшифровка в WaiComputer",
    libraryAlt: "Библиотека записей WaiComputer",
    macEyebrow: "WaiComputer для macOS",
    macTitle: "Ваша память начинается на Mac.",
    macBody:
      "Записывайте обе стороны разговора, диктуйте в любом приложении и сохраняйте каждую мысль в общей памяти.",
    macMeta: "Для macOS 14 и новее",
    alsoAvailable: "Также доступно",
    privacy: "Без фоновой записи. Вы сами решаете, когда начать.",
    platformWebTestId: "platform-web-ru",
    platformMeta: {
      web: "Браузер",
      iphone: "iPhone, бета",
    },
    finalTitle: "Начните с первой записи.",
    finalBody: "Бесплатно. В Pro нет недельного лимита на расшифровку, а записи хранятся без срока.",
    privacyLink: "Конфиденциальность",
    privacyHref: "/ru/privacy",
    termsLink: "Оферта",
    termsHref: "/ru/terms",
    benchmarkLink: "Тест распознавания речи",
    benchmarkHref: "/ru/benchmarks/dictation",
  },
} as const;

export function LandingPage({ locale, legal }: LandingPageProps) {
  const t = copy[locale];
  const suffix = locale === "ru" ? "-ru" : "";
  const macUrl = locale === "ru" ? MAC_DMG_URL_RU : MAC_DMG_URL;

  return (
    <main id="main" className={styles.landing}>
      <header className={styles.nav}>
        <Link href={t.home} className={styles.brand} aria-label={t.homeLabel}>
          <span className={styles.brandMark} aria-hidden="true" />
          <span className={styles.brandWord}>WaiComputer</span>
        </Link>
        <nav
          className={styles.navLinks}
          aria-label={locale === "ru" ? "Основная навигация" : "Primary navigation"}
        >
          <a href="#memory" className={styles.navLink}>
            {t.product}
          </a>
          <Link href={t.pricingHref} className={styles.navLink}>
            {t.pricing}
          </Link>
          <ThemeToggle locale={locale} />
          <LocaleSwitcher current={locale} />
          <Link href="/login" className={styles.signin}>
            {t.signIn}
          </Link>
          <Link href="/register" className={styles.getStarted}>
            {t.startFree}
          </Link>
        </nav>
      </header>

      <section className={styles.hero} aria-labelledby={`hero-title${suffix}`}>
        <div className={styles.heroAtmosphere} aria-hidden="true">
          <Image
            className={styles.heroAtmosphereLight}
            src="/landing/memory-lens-light-v1.webp"
            alt=""
            fill
            sizes="(max-width: 720px) 100vw, 95vw"
            priority
          />
          <Image
            className={styles.heroAtmosphereDark}
            src="/landing/memory-lens-dark-v1.webp"
            alt=""
            fill
            sizes="(max-width: 720px) 100vw, 95vw"
            priority
          />
        </div>
        <div className={styles.heroCopy}>
          <Image
            className={styles.heroIcon}
            src="/app-icon-320.png"
            width={80}
            height={80}
            priority
            alt=""
          />
          <p className={styles.heroEyebrow}>{t.heroEyebrow}</p>
          <h1 id={`hero-title${suffix}`} className={styles.headline}>
            {t.heroTitle}
          </h1>
          <p className={styles.subhead}>{t.heroBody}</p>
          <div className={styles.heroActions}>
            <a
              href={macUrl}
              download
              className={styles.primaryCta}
              data-testid={`download-mac${suffix}`}
            >
              {t.downloadMac}
            </a>
            <Link
              href="/dashboard"
              className={styles.secondaryCta}
              data-testid={`download-web${suffix}`}
            >
              {t.web}
            </Link>
          </div>
        </div>
      </section>

      <section id="memory" className={styles.memorySection} aria-labelledby={`memory-title${suffix}`}>
        <header className={styles.storyHeader}>
          <p className={styles.eyebrow}>{t.journeyEyebrow}</p>
          <h2 id={`memory-title${suffix}`} className={styles.sectionTitle}>
            {t.journeyTitle}
          </h2>
        </header>
        <ol className={styles.memoryJourney}>
          {t.steps.map((step) => (
            <li className={styles.memoryStep} key={step.number}>
              <span className={styles.memoryNode} aria-hidden="true">
                {step.number}
              </span>
              <div>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className={styles.productSection} aria-labelledby={`product-title${suffix}`}>
        <header className={styles.productHeader}>
          <div>
            <p className={styles.eyebrow}>{t.productEyebrow}</p>
            <h2 id={`product-title${suffix}`} className={styles.sectionTitle}>
              {t.productTitle}
            </h2>
          </div>
          <p>{t.productBody}</p>
        </header>

        <div className={styles.productWindows}>
          <figure className={styles.productWindowPrimary}>
            <Image
              src="/screenshots/recording-detail.png"
              alt={t.detailAlt}
              width={1400}
              height={875}
              sizes="(max-width: 760px) 94vw, 86vw"
            />
          </figure>
          <figure className={styles.productWindowSecondary}>
            <Image
              src="/screenshots/dashboard-library.png"
              alt={t.libraryAlt}
              width={1400}
              height={875}
              sizes="(max-width: 760px) 88vw, 58vw"
            />
          </figure>
        </div>
      </section>

      <section className={styles.macSection} aria-labelledby={`mac-title${suffix}`}>
        <div className={styles.macVisual} aria-hidden="true">
          <Image
            className={styles.macAppIcon}
            src="/app-icon-320.png"
            width={220}
            height={220}
            alt=""
          />
          <span className={styles.macVisualLabel}>WaiComputer · macOS</span>
        </div>
        <div className={styles.macContent}>
          <p className={styles.eyebrow}>{t.macEyebrow}</p>
          <h2 id={`mac-title${suffix}`} className={styles.sectionTitle}>
            {t.macTitle}
          </h2>
          <p className={styles.macBody}>{t.macBody}</p>
          <div className={styles.macActions}>
            <a
              href={macUrl}
              download
              className={styles.primaryCta}
              data-testid={`download-mac-secondary${suffix}`}
            >
              {t.downloadMac}
            </a>
            <span className={styles.macMeta}>{t.macMeta}</span>
          </div>
          <div
            className={styles.secondaryPlatforms}
            aria-label={locale === "ru" ? "Другие платформы" : "Other platforms"}
          >
            <span>{t.alsoAvailable}</span>
            <Link href="/dashboard" data-testid={t.platformWebTestId}>
              {t.platformMeta.web}
            </Link>
            <a href={TESTFLIGHT_URL} data-testid={`download-ios${suffix}`}>
              {t.platformMeta.iphone}
            </a>
          </div>
          <p className={styles.privacyLine}>
            <CircleCheck size={16} strokeWidth={1.8} aria-hidden="true" />
            {t.privacy}
          </p>
        </div>
      </section>

      <section className={styles.finalCta} aria-labelledby={`final-title${suffix}`}>
        <div>
          <h2 id={`final-title${suffix}`}>{t.finalTitle}</h2>
          <p>{t.finalBody}</p>
        </div>
        <Link href="/register" className={styles.primaryCta}>
          {t.startFree}
        </Link>
      </section>

      {legal}

      <footer className={styles.footer}>
        <span>© {CURRENT_YEAR} WaiWai</span>
        <div>
          <Link href={t.privacyHref}>{t.privacyLink}</Link>
          <Link href={t.termsHref}>{t.termsLink}</Link>
          <Link href={t.benchmarkHref}>{t.benchmarkLink}</Link>
          <a href="mailto:hi@waiwai.is">hi@waiwai.is</a>
        </div>
      </footer>
    </main>
  );
}
