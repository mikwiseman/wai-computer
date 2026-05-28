import Link from "next/link";
import Image from "next/image";
import styles from "../page.module.css";

const SUPPORT_EMAIL = "hi@waiwai.is";
const SUPPORT_PHONE = "+7 (936) 316-39-61";
const SELLER_NAME = 'ООО "ВАЙВАЙ"';
const SELLER_OGRN = "1257700218500";
const SELLER_INN = "9714075304";
const SELLER_ADDRESS = "г. Москва, ул. Большая Садовая, 5/1, 4 этаж";

function PaymentMarks() {
  return (
    <div className={styles.paymentMarks} aria-label="Принимаемые способы оплаты">
      <span className={styles.paymentMark}>
        <Image className={styles.paymentLogo} src="/payment-logos/mir.svg" alt="МИР" width={78} height={34} />
      </span>
      <span className={styles.paymentMark}>
        <Image className={styles.paymentLogo} src="/payment-logos/visa.svg" alt="Visa" width={78} height={34} />
      </span>
      <span className={styles.paymentMark}>
        <Image
          className={styles.paymentLogo}
          src="/payment-logos/mastercard.svg"
          alt="Mastercard"
          width={126}
          height={34}
        />
      </span>
      <a
        className={`${styles.paymentMark} ${styles.paymentBankMark}`}
        href="https://www.tbank.ru/"
        target="_blank"
        rel="noopener noreferrer"
      >
        <Image
          className={styles.paymentLogo}
          src="/payment-logos/tbank-tpay.svg"
          alt="Т-Банк T-Pay"
          width={154}
          height={34}
        />
        <span className={styles.paymentLogoCaption}>tbank.ru</span>
      </a>
    </div>
  );
}

interface PaymentComplianceSectionProps {
  title: string;
  eyebrow: string;
}

export function PaymentComplianceSection({ title, eyebrow }: PaymentComplianceSectionProps) {
  const titleId = title === "Оплата в рублях" ? "ru-payment-title" : "ru-payment-docs-title";

  return (
    <section className={`${styles.section} ${styles.complianceSection}`} aria-labelledby={titleId}>
      <header className={styles.sectionHeader}>
        <p className={styles.eyebrow}>{eyebrow}</p>
        <h2 id={titleId} className={styles.sectionTitle}>
          {title}
        </h2>
      </header>

      <div className={styles.complianceGrid}>
        <article className={styles.complianceCard}>
          <h3>Способы оплаты</h3>
          <PaymentMarks />
          <p>
            Рублевая оплата Pro проходит через Т-Банк: принимаются карты МИР,
            Visa и Mastercard, а также T-Pay, если он доступен на стороне банка.
          </p>
        </article>

        <article className={styles.complianceCard}>
          <h3>Цифровая услуга</h3>
          <p>
            WaiComputer — цифровая услуга и программное обеспечение WaiWai.
            Страна разработки и предоставления услуги: Россия. Физической
            доставки нет; доступ предоставляется после успешной оплаты.
          </p>
        </article>

        <article className={styles.complianceCard}>
          <h3>Возврат и поддержка</h3>
          <p>
            Отмена подписки, возврат, порядок оплаты и претензии описаны в{" "}
            <Link href="/ru/terms">публичной оферте</Link>. Поддержка:{" "}
            <a href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a>,{" "}
            <a href={`tel:${SUPPORT_PHONE.replace(/[^\d+]/g, "")}`}>{SUPPORT_PHONE}</a>.
          </p>
        </article>

        <article className={styles.complianceCard}>
          <h3>Продавец</h3>
          <dl className={styles.sellerDetails}>
            <div>
              <dt>Организация</dt>
              <dd>{SELLER_NAME}</dd>
            </div>
            <div>
              <dt>ОГРН</dt>
              <dd>{SELLER_OGRN}</dd>
            </div>
            <div>
              <dt>ИНН</dt>
              <dd>ИНН: {SELLER_INN}</dd>
            </div>
            <div>
              <dt>Адрес</dt>
              <dd>{SELLER_ADDRESS}</dd>
            </div>
          </dl>
        </article>
      </div>
    </section>
  );
}
