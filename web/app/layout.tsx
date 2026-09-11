import type { Metadata } from "next";
import { Inter, Instrument_Serif } from "next/font/google";
import { AuthProvider } from "@/lib/auth/AuthContext";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const instrumentSerif = Instrument_Serif({
  variable: "--font-instrument-serif",
  weight: "400",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "RiskWise 2.0 — Supply Chain Risk Intelligence",
  description: "Enterprise multi-tier supply chain risk intelligence and autonomous mitigation platform.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${instrumentSerif.variable} h-full antialiased dark`}
    >
      <body className="min-h-full flex flex-col bg-[#08090A] text-slate-100 font-sans selection:bg-blue-500/30 selection:text-blue-200">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}

