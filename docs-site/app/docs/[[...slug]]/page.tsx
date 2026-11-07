import { source } from '@/lib/source';
import { notFound } from 'next/navigation';
import { DocsPage, DocsBody, DocsTitle, DocsDescription } from 'fumadocs-ui/layouts/docs/page';
import type { Metadata } from 'next';

type Props = { params: Promise<{ slug?: string[] }> };

export function generateStaticParams() {
  return source.generateParams();
}

export function generateMetadata({ params }: Props): Promise<Metadata> {
  return params.then(({ slug }) => {
    const page = source.getPage(slug ?? []);
    if (!page) return {};
    return { title: page.data.title, description: page.data.description };
  });
}

export default async function Page({ params }: Props) {
  const { slug } = await params;
  const page = source.getPage(slug ?? []);
  if (!page) notFound();

  const Body = page.data.body;
  return (
    <DocsPage toc={page.data.toc}>
      <DocsTitle>{page.data.title}</DocsTitle>
      {page.data.description && <DocsDescription>{page.data.description}</DocsDescription>}
      <DocsBody><Body /></DocsBody>
    </DocsPage>
  );
}
