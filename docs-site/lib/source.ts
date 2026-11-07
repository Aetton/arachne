import { defineDocs } from 'fumadocs-mdx/macro';
import { loader } from 'fumadocs-core/source';

// The only editable content lives in ../docs; npm run sync prepares this generated directory.
const docs = defineDocs({ dir: 'content/docs' });

export const source = loader({
  baseUrl: '/docs',
  source: docs.toFumadocsSource(),
});
