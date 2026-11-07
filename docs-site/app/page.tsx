import Link from 'next/link';

// Static export cannot do a server-side redirect. A plain entry page keeps
// GitHub Pages root usable and takes readers directly to the real reference.
export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-4 px-6">
      <h1 className="text-3xl font-semibold">Arachne · Документация</h1>
      <p>Полный справочник находится в разделе документации, с постоянным деревом страниц и поиском.</p>
      <Link className="font-medium underline" href="/docs/ru">Открыть справочник →</Link>
    </main>
  );
}
