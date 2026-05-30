import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Logo } from "@/components/Logo";
import { AuthButtons } from "@/components/AuthButtons";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "InterviewSignal",
  description: "AI-native technical interviews. Free, open source, repo-native.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-zinc-950">
        <ClerkProvider>
          <header className="border-b border-zinc-800 bg-zinc-950">
            <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">

              {/* Logo + wordmark */}
              <a href="/" className="flex items-center gap-2.5 shrink-0">
                <Logo size={28} />
                <span className="text-sm font-semibold text-white tracking-tight">
                  InterviewSignal
                </span>
              </a>

              {/* Centered nav */}
              <nav className="hidden items-center gap-6 md:flex absolute left-1/2 -translate-x-1/2">
                <a href="/" className="text-sm text-zinc-400 hover:text-white transition-colors">Home</a>
                <a href="/problems" className="text-sm text-zinc-400 hover:text-white transition-colors">Problems</a>
                <a
                  href="https://github.com/NikhilSKashyap/interviewsignal"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-zinc-400 hover:text-white transition-colors"
                >
                  GitHub
                </a>
              </nav>

              {/* Right — auth */}
              <div className="flex items-center gap-3 shrink-0">
                <AuthButtons />
              </div>
            </div>
          </header>
          {children}
        </ClerkProvider>
      </body>
    </html>
  );
}
