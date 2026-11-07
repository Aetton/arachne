'use client';

import { useDocsSearch } from 'fumadocs-core/search/client';
import { staticClient } from 'fumadocs-core/search/client/orama-static';
import {
  SearchDialog, SearchDialogOverlay, SearchDialogContent, SearchDialogHeader,
  SearchDialogIcon, SearchDialogInput, SearchDialogClose, SearchDialogList,
  SearchDialogFooter, type SharedProps,
} from 'fumadocs-ui/components/dialog/search';

export function StaticSearchDialog(props: SharedProps) {
  const { search, setSearch, query } = useDocsSearch({ client: staticClient({ from: `${process.env.NEXT_PUBLIC_DOCS_BASE_PATH || ''}/api/search` }) });

  return (
    <SearchDialog search={search} onSearchChange={setSearch} isLoading={query.isLoading} {...props}>
      <SearchDialogOverlay />
      <SearchDialogContent>
        <SearchDialogHeader>
          <SearchDialogIcon />
          <SearchDialogInput />
          <SearchDialogClose />
        </SearchDialogHeader>
        <SearchDialogList items={query.data !== 'empty' ? query.data : null} />
      </SearchDialogContent>
      <SearchDialogFooter />
    </SearchDialog>
  );
}
