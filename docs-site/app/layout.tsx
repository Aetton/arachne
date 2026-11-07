import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { RootProvider } from 'fumadocs-ui/provider/next';
import { StaticSearchDialog } from '@/components/static-search';
import './globals.css';

export const metadata: Metadata = {
  title: { default: 'Arachne · Справочник', template: '%s | Arachne' },
  description: 'Справочник Arachne: сценарии, пауки, права, Golden Images, CI/CD и API.',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru" suppressHydrationWarning>
      <body className="flex min-h-screen flex-col">
        <RootProvider search={{ SearchDialog: StaticSearchDialog }}>
          {children}
        </RootProvider>
      </body>
    </html>
  );
}
