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
    heroTitle: "Build a second memory.",
    heroBody:
      "Meetings, thoughts, and notes become clear summaries, actions, and answers.",
    primary: "Start free",
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
      "Recording, dictation, summaries, search, and MCP — one connected memory.",
    detailAlt: "WaiComputer recording summary and transcript",
    libraryAlt: "WaiComputer memory library",
    platformsTitle: "Your memory, wherever you work.",
    privacy: "Recording starts only when you tell it to.",
    platformWebTestId: "platform-web",
    platformMeta: {
      mac: "Native · macOS 14+",
      web: "No install",
      iphone: "TestFlight",
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
    heroTitle: "Не держите всё в голове.",
    heroBody:
      "Записывайте встречи и голосовые заметки. WaiComputer расшифрует речь, выделит главное и поможет быстро найти нужное.",
    primary: "Попробовать бесплатно",
    web: "Открыть в браузере",
    journeyEyebrow: "Как работает WaiComputer",
    journeyTitle: "Запишите один раз. Найдите в любой момент.",
    steps: [
      { number: "01", title: "Запись", body: "Запишите встречу или надиктуйте мысль." },
      { number: "02", title: "Главное", body: "Получите расшифровку, краткий итог и список задач." },
      { number: "03", title: "Поиск", body: "Ищите по словам или задавайте вопросы по своим записям." },
    ],
    productEyebrow: "Всё в одном месте",
    productTitle: "Откройте запись — сразу увидите главное.",
    productBody:
      "Запись, расшифровка, краткий итог и задачи — в одном окне. Все записи собраны в общей библиотеке.",
    detailAlt: "Краткий итог и расшифровка в WaiComputer",
    libraryAlt: "Библиотека записей WaiComputer",
    platformsTitle: "На Mac, iPhone и в браузере.",
    privacy: "Без фоновой записи — вы сами решаете, когда начать.",
    platformWebTestId: "platform-web-ru",
    platformMeta: {
      mac: "macOS 14+",
      web: "Без установки",
      iphone: "Бета · TestFlight",
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
            {t.primary}
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
          <h1 id={`hero-title${suffix}`} className={styles.headline}>
            {t.heroTitle}
          </h1>
          <p className={styles.subhead}>{t.heroBody}</p>
          <div className={styles.heroActions}>
            <Link
              href="/register"
              className={styles.primaryCta}
              data-testid={`primary-cta${suffix}`}
            >
              {t.primary}
            </Link>
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

      <section className={styles.platformSection} aria-labelledby={`platform-title${suffix}`}>
        <h2 id={`platform-title${suffix}`} className={styles.sectionTitle}>
          {t.platformsTitle}
        </h2>
        <div className={styles.platforms}>
          <a
            href={macUrl}
            download
            className={styles.platformChip}
            data-testid={`download-mac${suffix}`}
          >
            <span>Mac</span>
            <small>{t.platformMeta.mac}</small>
          </a>
          <Link
            href="/dashboard"
            className={styles.platformChip}
            data-testid={t.platformWebTestId}
          >
            <span>{locale === "ru" ? "Браузер" : "Web"}</span>
            <small>{t.platformMeta.web}</small>
          </Link>
          <a
            href={TESTFLIGHT_URL}
            className={styles.platformChip}
            data-testid={`download-ios${suffix}`}
          >
            <span>iPhone</span>
            <small>{t.platformMeta.iphone}</small>
          </a>
        </div>
        <p className={styles.privacyLine}>
          <CircleCheck size={16} strokeWidth={1.8} aria-hidden="true" />
          {t.privacy}
        </p>
      </section>

      <section className={styles.finalCta} aria-labelledby={`final-title${suffix}`}>
        <div>
          <h2 id={`final-title${suffix}`}>{t.finalTitle}</h2>
          <p>{t.finalBody}</p>
        </div>
        <Link href="/register" className={styles.primaryCta}>
          {t.primary}
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
