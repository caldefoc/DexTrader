"use client";
"use client";
import { MarketView } from "../app/dashboard/page";

type Props = {
  view: MarketView;
  onChange: (view: MarketView) => void;
};

export default function GainersLosersToggle(props: Props) {
  const view = props.view;
  const setView = props.onChange;

  return (
    <div className="inline-flex rounded-md border border-slate-800 bg-slate-950/60 text-xs">
      <button
        type="button"
        onClick={() => setView("all")}
        className={
          "px-3 py-1.5 rounded-l-md " +
          (view === "all"
            ? "bg-primary text-primary-foreground"
            : "text-gray-300 hover:bg-slate-900")
        }
      >
        All
      </button>
      <button
        type="button"
        onClick={() => setView("tracked")}
        className={
          "px-3 py-1.5 border-l border-slate-800 " +
          (view === "tracked"
            ? "bg-primary text-primary-foreground"
            : "text-gray-300 hover:bg-slate-900")
        }
      >
        Tracked
      </button>
      <button
        type="button"
        onClick={() => setView("volume")}
        className={
          "px-3 py-1.5 border-l border-slate-800 " +
          (view === "volume"
            ? "bg-primary text-primary-foreground"
            : "text-blue-400 hover:bg-slate-900")
        }
      >
        Volume
      </button>
      <button
        type="button"
        onClick={() => setView("gainers")}
        className={
          "px-3 py-1.5 border-l border-slate-800 " +
          (view === "gainers"
            ? "bg-primary text-primary-foreground"
            : "text-emerald-400 hover:bg-slate-900")
        }
      >
        Gainers
      </button>
      <button
        type="button"
        onClick={() => setView("losers")}
        className={
          "px-3 py-1.5 rounded-r-md border-l border-slate-800 " +
          (view === "losers"
            ? "bg-primary text-primary-foreground"
            : "text-red-400 hover:bg-slate-900")
        }
      >
        Losers
      </button>
    </div>
  );
}
