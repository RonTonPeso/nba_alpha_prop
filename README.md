# nba_alpha_prop

An NBA player-prop forecasting system. XGBoost feature predictor wrapped in a hierarchical Bayesian model that produces full posterior distributions, compared against live Kalshi prediction-market prices to surface positive-EV opportunities and track its own calibration over time. LLM-classified injury news updates priors through a lineup-conditional layer.

This is a portfolio project, not a trading system. No real money, all trades are paper trades against live market quotes. The goal is modeling and engineering rigor, not beating sharp markets.

## Status

Under construction. The project is being built in milestones (M0 through M10). Currently working on M0: repo skeleton, local dev environment, CI, deployment scaffolding.

Expect this README to grow significantly once the dashboard is live: screenshots, a demo link, architecture summary, model card link, and backtest results.

## License

MIT
