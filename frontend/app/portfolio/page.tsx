import PortfolioTable from "../../components/PortfolioTable";
import BaseTokensPanel from "../../components/BaseTokensPanel";

export default function PortfolioPage() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold">Portfolio</h1>
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
        <PortfolioTable />
        <BaseTokensPanel />
      </div>
    </div>
  );
}

