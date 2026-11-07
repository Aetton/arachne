// GitHub Pages has no server-side redirect. The root immediately opens the reference.
export default function Home() {
  const target = `${process.env.DOCS_BASE_PATH || ''}/docs/ru/`;
  return (
    <main>
      <meta httpEquiv="refresh" content={`0;url=${target}`} />
      <a href={target}>Перейти в справочник Arachne</a>
    </main>
  );
}
