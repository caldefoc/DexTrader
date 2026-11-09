import PortfolioTable from "../../components/PortfolioTable";
import BaseTokensPanel from "../../components/BaseTokensPanel";
import DemoPortfolio from "../../components/DemoPortfolio";
import { DEMO_MODE } from "../../constants/config";

export default function PortfolioPage() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold">Portfolio</h1>
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
        {DEMO_MODE ? <DemoPortfolio /> : <PortfolioTable />}
        <BaseTokensPanel />
      </div>
    </div>
  );
}
