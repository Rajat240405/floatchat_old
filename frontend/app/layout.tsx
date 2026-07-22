import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FloatChat — AI Ocean Intelligence",
  description:
    "Conversational AI for querying live Argo biogeochemical oceanographic data. Ask about oxygen, chlorophyll, temperature, salinity, and more.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
