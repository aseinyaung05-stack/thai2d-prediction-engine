"use client";

import React, { createContext, useContext, useState } from "react";

export type Lang = "mm" | "en";

const DICT = {
  mm: {
    title: "ထိုင်း 2D ခန့်မှန်းချက် အင်ဂျင်",
    subtitle: "သမိုင်းဒေတာ • စာရင်းအင်း ခွဲခြမ်းစိတ်ဖြာမှု • မော်ဒယ် အဆင့်သတ်မှတ်ချက်",
    today: "ဒီနေ့ ထိုင်း 2D မော်ဒယ် ခွဲခြမ်းစိတ်ဖြာချက်",
    morning: "မနက်ပိုင်း ၁၂:၀၀",
    afternoon: "ညနေပိုင်း ၄:၃၀",
    highestSection: "အမှတ်အများဆုံး Section (မော်ဒယ်)",
    topCandidates: "ထိပ်တန်း ကဏ္ဍများ",
    sectionRanking: "SECTION အဆင့်သတ်မှတ်ချက်",
    top10: "ထိပ် ၁၀ မော်ဒယ်အမှတ် (00–99)",
    number: "အမှတ်",
    section: "Section",
    score: "မော်ဒယ်အမှတ်",
    rank: "အဆင့်",
    history: "ရလဒ် မှတ်တမ်း",
    backtest: "Backtest စွမ်းဆောင်ရည်",
    status: "Model အခြေအနေ",
    dashboard: "ဒက်ရှ်ဘုတ်",
    disclaimer:
      "ဤ application သည် သမိုင်းဒေတာအပေါ် အခြေခံသော စာရင်းအင်း ခွဲခြမ်းစိတ်ဖြာမှုသာ ဖြစ်သည်။ မော်ဒယ်အမှတ်များမှာ ခန့်မှန်းချက်များသာဖြစ်ပြီး အာမခံချက် မဟုတ်ပါ။",
    stale: "Live source မရနိုင် — cache ဒေတာ ပြသထားပါသည်။",
    noData: "ဒေတာ မရှိပါ။",
    apiDown: "API server နှင့် ချိတ်ဆက်မရပါ။",
    nextSession: "နောက်မည့် Session",
    syncNow: "ဒေတာ အသစ်တင်",
    date: "ရက်စွဲ",
    session: "Session",
    result: "2D",
    source: "အရင်းအမြစ်",
    time: "အချိန် (UTC)",
    dataQuality: "ဒေတာ အရည်အသွေး",
    records: "မှတ်တမ်း အရေအတွက်",
    model: "Model",
    version: "ဗားရှင်း",
    lastTraining: "နောက်ဆုံး Train ချိန်",
    lastSync: "နောက်ဆုံး Sync",
    agreement: "Model သဘောတူညီမှု",
    edgeNone: "ယုံကြည်စိတ်ချရသော ခန့်မှန်းအားသတ်မှတ်ချက် မတွေ့ရှိပါ။",
  },
  en: {
    title: "Thai 2D Prediction Engine",
    subtitle: "Historical Data • Statistical Analysis • Model Ranking",
    today: "TODAY'S THAI 2D MODEL ANALYSIS",
    morning: "12:00 PM Session",
    afternoon: "4:30 PM Session",
    highestSection: "Highest Model-Scored Section",
    topCandidates: "Top Candidates",
    sectionRanking: "SECTION RANKING",
    top10: "TOP 10 MODEL-SCORED NUMBERS (00–99)",
    number: "Number",
    section: "Section",
    score: "Model Score",
    rank: "Rank",
    history: "Latest Results",
    backtest: "Backtest Performance",
    status: "Model Status",
    dashboard: "Dashboard",
    disclaimer:
      "This application provides statistical analysis based on historical market/2D data. Model scores are estimates, not guarantees. Historical performance does not guarantee future results.",
    stale: "Live source unavailable — using cached data.",
    noData: "No valid data available.",
    apiDown: "Cannot reach the API server.",
    nextSession: "Next Session",
    syncNow: "Sync Now",
    date: "Date",
    session: "Session",
    result: "2D",
    source: "Source",
    time: "Time (UTC)",
    dataQuality: "Data Quality",
    records: "Record Count",
    model: "Model",
    version: "Version",
    lastTraining: "Last Training",
    lastSync: "Last Sync",
    agreement: "Model Agreement",
    edgeNone: "No reliable predictive edge detected.",
  },
} as const;

export type DictKey = keyof (typeof DICT)["en"];

const LangContext = createContext<{
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (k: DictKey) => string;
}>({ lang: "mm", setLang: () => {}, t: () => "" });

export function LangProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLang] = useState<Lang>("mm");
  const t = (k: DictKey) => DICT[lang][k] ?? DICT.en[k];
  return (
    <LangContext.Provider value={{ lang, setLang, t }}>{children}</LangContext.Provider>
  );
}

export const useLang = () => useContext(LangContext);
