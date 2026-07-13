import type { Metadata } from "next";

export const metadata: Metadata = {
  alternates: {
    canonical: "https://wai.computer/ru",
    languages: {
      en: "https://wai.computer",
      ru: "https://wai.computer/ru",
    },
  },
};

export default function RuLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // The root layout guesses <html lang> from Accept-Language, which is wrong
  // for an EN-configured browser on /ru/* (and vice versa). URL wins: stamp
  // the root element before paint so screen readers and translate prompts see
  // Russian, and keep the inner lang fence for the SSR snapshot.
  return (
    <div lang="ru">
      <script
        dangerouslySetInnerHTML={{
          __html: 'document.documentElement.lang="ru";',
        }}
      />
      {children}
    </div>
  );
}
