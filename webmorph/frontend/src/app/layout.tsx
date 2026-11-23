import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "WebMorph — Browser Workspace",
  description: "Scout websites, answer adaptive forms, and steer a live browser from one workspace.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
