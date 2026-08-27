import type { Metadata } from "next";
import MCQClient from "./MCQClient";

export const metadata: Metadata = {
  title: "CA MCQ Practice — Foundation, Intermediate & Final",
  description:
    "Timed MCQ practice sets for CA Foundation, Intermediate & Final, built to mirror the real exam pattern with full explanations for every question.",
  alternates: { canonical: "/mcq" },
};

export default function MCQPage() {
  return <MCQClient />;
}
