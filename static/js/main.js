// Using an IIFE to avoid polluting the global scope
(function() {
    // Wait for the DOM to be fully loaded before running any script
    document.addEventListener('DOMContentLoaded', () => {

        // Get all necessary DOM elements once the DOM is ready
        const editor = document.getElementById('simulation-editor');
        const resultsOutput = document.getElementById('results-output');
        const profitLossOutput = document.getElementById('profit-loss-output');
        const nodeFilter = document.getElementById('node-filter');
        const itemFilter = document.getElementById('item-filter');
        const dayFrom = document.getElementById('day-from');
        const dayTo = document.getElementById('day-to');
        const downloadResultsCsvBtn = document.getElementById('download-results-csv');
        const downloadPlCsvBtn = document.getElementById('download-pl-csv');
        const summaryOutput = document.getElementById('summary-output');
        const downloadSummaryCsvBtn = document.getElementById('download-summary-csv');
        const runButton = document.querySelector('.run-button');
        const tabButtons = document.querySelectorAll('.tab-button');

        // This variable will hold the complete simulation results
        let fullResultsData = [];
        let fullProfitLoss = [];
        let fullSummary = null;

        // Load default JSON from external file and initialize editor
        fetch('/static/default_input.json')
            .then(resp => resp.json())
            .then(sampleInput => {
                editor.value = JSON.stringify(sampleInput, null, 4);
            })
            .catch(err => {
                console.error('Failed to load default_input.json', err);
                editor.value = '{\n  "planning_horizon": 30,\n  "products": [],\n  "nodes": [],\n  "network": [],\n  "customer_demand": []\n}';
            });

        // --- Function Definitions ---

        function formatNumber(num) {
            if (num === undefined || num === null) return '-';
            return Math.round(num).toLocaleString();
        }

        function openTab(evt, tabName) {
            const tabContents = document.getElementsByClassName("tab-content");
            for (let i = 0; i < tabContents.length; i++) {
                tabContents[i].style.display = "none";
            }
            const tabButtons = document.getElementsByClassName("tab-button");
            for (let i = 0; i < tabButtons.length; i++) {
                tabButtons[i].className = tabButtons[i].className.replace(" active", "");
            }
            document.getElementById(tabName).style.display = "block";
            
            // The event might be null on the first load
            if (evt && evt.currentTarget) {
                evt.currentTarget.className += " active";
            } else {
                document.querySelector(`.tab-button[data-tab='${tabName}']`).classList.add('active');
            }
        }

        function computeClientSummary(results, profitLoss, inputJson) {
            try {
                const nodeTypeMap = {};
                (inputJson.nodes || []).forEach(n => { nodeTypeMap[n.name] = n.node_type; });

                const types = ["store","warehouse","factory","material"];
                const totals = {};
                types.forEach(t => totals[t] = { demand:0, sales:0, shortage:0, end:0 });
                const topShort = {};
                const boTotals = [];

                results.forEach(day => {
                    let bo = 0;
                    const nodes = day.nodes || {};
                    Object.keys(nodes).forEach(nodeName => {
                        const ntype = nodeTypeMap[nodeName];
                        const bucket = totals[ntype];
                        const items = nodes[nodeName] || {};
                        Object.keys(items).forEach(item => {
                            const m = items[item] || {};
                            const d = +m.demand || 0, s = +m.sales || 0, sh = +m.shortage || 0, end = +m.end_stock || 0;
                            if (bucket) {
                                bucket.demand += d; bucket.sales += s; bucket.shortage += sh; bucket.end += end;
                            }
                            if (ntype === 'store') {
                                topShort[item] = (topShort[item]||0) + sh;
                                bo += (+m.backorder_balance || 0);
                            }
                        });
                    });
                    boTotals.push(bo);
                });

                const days = Math.max(1, results.length || 0);
                const avgOnHandByType = {};
                types.forEach(t => { avgOnHandByType[t] = (totals[t].end || 0) / days; });
                const storeDemand = totals.store.demand;
                const storeSales = totals.store.sales;
                const fillRate = storeDemand > 0 ? (storeSales / storeDemand) : 1.0;

                let revenueTotal = 0, materialTotal = 0, flowTotal = 0, stockTotal = 0, penaltyStockout = 0, penaltyBackorder = 0;
                (profitLoss || []).forEach(pl => {
                    revenueTotal += (+pl.revenue || 0);
                    materialTotal += (+pl.material_cost || 0);
                    const fc = pl.flow_costs || {}; const sc = pl.stock_costs || {};
                    Object.values(fc).forEach(v => { flowTotal += (+v || 0); });
                    Object.values(sc).forEach(v => { stockTotal += (+v || 0); });
                    const pc = pl.penalty_costs || {};
                    penaltyStockout += (+pc.stockout || 0);
                    penaltyBackorder += (+pc.backorder || 0);
                });
                const penaltyTotal = penaltyStockout + penaltyBackorder;
                const costTotal = materialTotal + flowTotal + stockTotal + penaltyTotal;
                const profitTotal = revenueTotal - costTotal;

                const topShortageItems = Object.entries(topShort)
                    .sort((a,b) => b[1]-a[1]).slice(0,5)
                    .map(([item, shortage]) => ({ item, shortage }));

                const boPeak = boTotals.length ? Math.max(...boTotals) : 0;
                const boPeakDay = boTotals.length ? (boTotals.indexOf(boPeak) + 1) : 0;

                return {
                    planning_days: days,
                    fill_rate: fillRate,
                    store_demand_total: storeDemand,
                    store_sales_total: storeSales,
                    customer_shortage_total: totals.store.shortage,
                    network_shortage_total: totals.warehouse.shortage + totals.factory.shortage + totals.material.shortage,
                    avg_on_hand_by_type: avgOnHandByType,
                    backorder_peak: boPeak,
                    backorder_peak_day: boPeakDay,
                    revenue_total: revenueTotal,
                    cost_total: costTotal,
                    penalty_stockout_total: penaltyStockout,
                    penalty_backorder_total: penaltyBackorder,
                    penalty_total: penaltyTotal,
                    profit_total: profitTotal,
                    profit_per_day_avg: days ? (profitTotal / days) : 0,
                    top_shortage_items: topShortageItems,
                };
            } catch (e) {
                console.warn('Client summary fallback failed:', e);
                return null;
            }
        }

        async function runSimulation() {
            resultsOutput.innerHTML = 'シミュレーションを実行中...';
            profitLossOutput.innerHTML = '';
            openTab(null, 'results'); // Switch to results tab immediately

            let requestBody;
            try {
                requestBody = JSON.parse(editor.value);
            } catch (e) {
                resultsOutput.innerHTML = `<div class="error-message">JSONの形式が正しくありません: ${e.message}</div>`;
                return;
            }

            try {
                const response = await fetch('/simulation', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(requestBody)
                });

                const data = await response.json();

                if (!response.ok) {
                    let errorText = `HTTPエラー: ${response.status}`;
                    if (data.detail) {
                        errorText += `\n${JSON.stringify(data.detail, null, 4)}`;
                    }
                    throw new Error(errorText);
                }

                fullResultsData = data.results;
                fullProfitLoss = data.profit_loss || [];
                fullSummary = data.summary || computeClientSummary(fullResultsData, fullProfitLoss, requestBody) || null;
                populateFilters(fullResultsData);
                applyFilters(); // This will call displayResultsTable
                displayProfitLossTable(fullProfitLoss);
                displaySummary(fullSummary);

            } catch (error) {
                resultsOutput.innerHTML = `<div class="error-message">エラーが発生しました: ${error.message}</div>`;
            }
        }

        function populateFilters(results) {
            const nodeSet = new Set();
            const itemSet = new Set();
            results.forEach(day => {
                for (const nodeName in day.nodes) {
                    nodeSet.add(nodeName);
                    for (const itemName in day.nodes[nodeName]) {
                        itemSet.add(itemName);
                    }
                }
            });

            nodeFilter.innerHTML = '<option value="all">All</option>';
            Array.from(nodeSet).sort().forEach(node => {
                nodeFilter.innerHTML += `<option value="${node}">${node}</option>`;
            });

            itemFilter.innerHTML = '<option value="all">All</option>';
            Array.from(itemSet).sort().forEach(item => {
                itemFilter.innerHTML += `<option value="${item}">${item}</option>`;
            });

            // Initialize day range
            const maxDay = results.length > 0 ? Math.max(...results.map(d => d.day)) : 1;
            dayFrom.min = 1; dayFrom.max = maxDay; dayFrom.value = 1;
            dayTo.min = 1; dayTo.max = maxDay; dayTo.value = maxDay;
        }

        function applyFilters() {
            const selectedNode = nodeFilter.value;
            const selectedItem = itemFilter.value;
            const from = Math.max(1, parseInt(dayFrom.value || '1', 10));
            const to = Math.max(from, parseInt(dayTo.value || String(from), 10));

            const filteredData = fullResultsData.map(day => {
                const newDay = { ...day, nodes: {} };
                if (!(day.day >= from && day.day <= to)) return { ...newDay, nodes: {} };
                for (const nodeName in day.nodes) {
                    if (selectedNode === 'all' || selectedNode === nodeName) {
                        const newNodeData = {};
                        for (const itemName in day.nodes[nodeName]) {
                            if (selectedItem === 'all' || selectedItem === itemName) {
                                newNodeData[itemName] = day.nodes[nodeName][itemName];
                            }
                        }
                        if (Object.keys(newNodeData).length > 0) {
                            newDay.nodes[nodeName] = newNodeData;
                        }
                    }
                }
                return newDay;
            }).filter(day => Object.keys(day.nodes).length > 0);

            displayResultsTable(filteredData);
        }

        function displayResultsTable(results) {
            if (!results || results.length === 0) {
                resultsOutput.innerHTML = '条件に一致する結果がありません。';
                return;
            }
            let tableHtml = '<table><thead><tr><th>Day</th><th>Node</th><th>Item</th><th>Start Stock</th><th>Incoming</th><th>Demand</th><th>Sales</th><th>Consumption</th><th>Produced</th><th>Shortage</th><th>Backorder</th><th>End Stock</th><th>Ordered</th></tr></thead><tbody>';

            results.forEach(dayResult => {
                const day = dayResult.day;
                for (const nodeName in dayResult.nodes) {
                    const nodeData = dayResult.nodes[nodeName];
                    for (const itemName in nodeData) {
                        const itemData = nodeData[itemName];
                        tableHtml += `<tr>
                            <td>${day}</td>
                            <td style="text-align: left;">${nodeName}</td>
                            <td style="text-align: left;">${itemName}</td>
                            <td>${formatNumber(itemData.start_stock)}</td>
                            <td>${formatNumber(itemData.incoming)}</td>
                            <td>${formatNumber(itemData.demand)}</td>
                            <td>${formatNumber(itemData.sales)}</td>
                            <td>${formatNumber(itemData.consumption)}</td>
                            <td>${formatNumber(itemData.produced)}</td>
                            <td>${formatNumber(itemData.shortage)}</td>
                            <td>${formatNumber(itemData.backorder_balance)}</td>
                            <td>${formatNumber(itemData.end_stock)}</td>
                            <td>${formatNumber(itemData.ordered_quantity)}</td>
                        </tr>`;
                    }
                }
            });

            tableHtml += '</tbody></table>';
            resultsOutput.innerHTML = tableHtml;
        }

        function displayProfitLossTable(profitLoss) {
            if (!profitLoss || profitLoss.length === 0) {
                profitLossOutput.innerHTML = '収支データがありません。';
                return;
            }

            let tableHtml = `
                <table>
                    <thead>
                        <tr class="pl-header-row-1">
                            <th rowspan="3">Day</th>
                            <th rowspan="3">Revenue</th>
                            <th rowspan="3">Material Cost</th>
                            <th colspan="8">Flow Costs</th>
                            <th colspan="8">Stock Costs</th>
                            <th colspan="2">Penalty Costs</th>
                            <th rowspan="3">Total Cost</th>
                            <th rowspan="3">Profit/Loss</th>
                        </tr>
                        <tr class="pl-header-row-2">
                            <th colspan="2">Material Transport</th>
                            <th colspan="2">Production</th>
                            <th colspan="2">Warehouse Transport</th>
                            <th colspan="2">Store Transport</th>
                            <th colspan="2">Material Storage</th>
                            <th colspan="2">Factory Storage</th>
                            <th colspan="2">Warehouse Storage</th>
                            <th colspan="2">Store Storage</th>
                            <th colspan="2">Penalty</th>
                        </tr>
                        <tr class="pl-header-row-3">
                            <th>Fixed</th><th>Variable</th>
                            <th>Fixed</th><th>Variable</th>
                            <th>Fixed</th><th>Variable</th>
                            <th>Fixed</th><th>Variable</th>
                            <th>Fixed</th><th>Variable</th>
                            <th>Fixed</th><th>Variable</th>
                            <th>Fixed</th><th>Variable</th>
                            <th>Fixed</th><th>Variable</th>
                            <th>Stockout</th><th>Backorder</th>
                        </tr>
                    </thead>
                    <tbody>
            `;

            profitLoss.forEach(pl => {
                tableHtml += `<tr>
                    <td>${pl.day}</td>
                    <td>${formatNumber(pl.revenue)}</td>
                    <td>${formatNumber(pl.material_cost)}</td>
                    <td>${formatNumber(pl.flow_costs.material_transport_fixed)}</td>
                    <td>${formatNumber(pl.flow_costs.material_transport_variable)}</td>
                    <td>${formatNumber(pl.flow_costs.production_fixed)}</td>
                    <td>${formatNumber(pl.flow_costs.production_variable)}</td>
                    <td>${formatNumber(pl.flow_costs.warehouse_transport_fixed)}</td>
                    <td>${formatNumber(pl.flow_costs.warehouse_transport_variable)}</td>
                    <td>${formatNumber(pl.flow_costs.store_transport_fixed)}</td>
                    <td>${formatNumber(pl.flow_costs.store_transport_variable)}</td>
                    <td>${formatNumber(pl.stock_costs.material_storage_fixed)}</td>
                    <td>${formatNumber(pl.stock_costs.material_storage_variable)}</td>
                    <td>${formatNumber(pl.stock_costs.factory_storage_fixed)}</td>
                    <td>${formatNumber(pl.stock_costs.factory_storage_variable)}</td>
                    <td>${formatNumber(pl.stock_costs.warehouse_storage_fixed)}</td>
                    <td>${formatNumber(pl.stock_costs.warehouse_storage_variable)}</td>
                    <td>${formatNumber(pl.stock_costs.store_storage_fixed)}</td>
                    <td>${formatNumber(pl.stock_costs.store_storage_variable)}</td>
                    <td>${formatNumber((pl.penalty_costs||{}).stockout)}</td>
                    <td>${formatNumber((pl.penalty_costs||{}).backorder)}</td>
                    <td>${formatNumber(pl.total_cost)}</td>
                    <td>${formatNumber(pl.profit_loss)}</td>
                </tr>`;
            });

            tableHtml += '</tbody></table>';
            profitLossOutput.innerHTML = tableHtml;
        }

        function toCsv(rows, headers) {
            const esc = (v) => {
                if (v === undefined || v === null) return '';
                const s = String(v);
                return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
            };
            const lines = [];
            lines.push(headers.map(esc).join(','));
            rows.forEach(r => lines.push(headers.map(h => esc(r[h])).join(',')));
            return lines.join('\n');
        }

        function exportSummaryCsv() {
            if (!fullSummary) return;
            const s = fullSummary;
            const rows = [{
                planning_days: s.planning_days,
                fill_rate: s.fill_rate,
                store_demand_total: s.store_demand_total,
                store_sales_total: s.store_sales_total,
                customer_shortage_total: s.customer_shortage_total,
                network_shortage_total: s.network_shortage_total,
                backorder_peak: s.backorder_peak,
                backorder_peak_day: s.backorder_peak_day,
                revenue_total: s.revenue_total,
                cost_total: s.cost_total,
                penalty_stockout_total: s.penalty_stockout_total || 0,
                penalty_backorder_total: s.penalty_backorder_total || 0,
                penalty_total: s.penalty_total || 0,
                profit_total: s.profit_total,
                profit_per_day_avg: s.profit_per_day_avg,
            }];
            const headers = Object.keys(rows[0]);
            const csv = toCsv(rows, headers);
            downloadBlob('summary.csv', csv);
        }

        function downloadBlob(filename, content, type='text/csv') {
            const blob = new Blob([content], { type });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = filename;
            document.body.appendChild(a); a.click();
            setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 0);
        }

        function exportResultsCsv() {
            const from = Math.max(1, parseInt(dayFrom.value || '1', 10));
            const to = Math.max(from, parseInt(dayTo.value || String(from), 10));
            const rows = [];
            fullResultsData.forEach(day => {
                if (!(day.day >= from && day.day <= to)) return;
                for (const node in day.nodes) {
                    for (const item in day.nodes[node]) {
                        const m = day.nodes[node][item];
                        rows.push({
                            Day: day.day,
                            Node: node,
                            Item: item,
                            StartStock: m.start_stock || 0,
                            Incoming: m.incoming || 0,
                            Demand: m.demand || 0,
                            Sales: m.sales || 0,
                            Consumption: m.consumption || 0,
                            Produced: m.produced || 0,
                            Shortage: m.shortage || 0,
                            Backorder: m.backorder_balance || 0,
                            EndStock: m.end_stock || 0,
                            Ordered: m.ordered_quantity || 0,
                        });
                    }
                }
            });
            const headers = [
                'Day','Node','Item','StartStock','Incoming','Demand','Sales','Consumption','Produced','Shortage','Backorder','EndStock','Ordered'
            ];
            const csv = toCsv(rows, headers);
            downloadBlob('results.csv', csv);
        }

        function exportPlCsv() {
            const rows = [];
            fullProfitLoss.forEach(pl => {
                rows.push({
                    Day: pl.day,
                    Revenue: pl.revenue,
                    MaterialCost: pl.material_cost,
                    Flow_Material_Fixed: pl.flow_costs.material_transport_fixed,
                    Flow_Material_Variable: pl.flow_costs.material_transport_variable,
                    Flow_Production_Fixed: pl.flow_costs.production_fixed,
                    Flow_Production_Variable: pl.flow_costs.production_variable,
                    Flow_Warehouse_Fixed: pl.flow_costs.warehouse_transport_fixed,
                    Flow_Warehouse_Variable: pl.flow_costs.warehouse_transport_variable,
                    Flow_Store_Fixed: pl.flow_costs.store_transport_fixed,
                    Flow_Store_Variable: pl.flow_costs.store_transport_variable,
                    Stock_Material_Fixed: pl.stock_costs.material_storage_fixed,
                    Stock_Material_Variable: pl.stock_costs.material_storage_variable,
                    Stock_Factory_Fixed: pl.stock_costs.factory_storage_fixed,
                    Stock_Factory_Variable: pl.stock_costs.factory_storage_variable,
                    Stock_Warehouse_Fixed: pl.stock_costs.warehouse_storage_fixed,
                    Stock_Warehouse_Variable: pl.stock_costs.warehouse_storage_variable,
                    Stock_Store_Fixed: pl.stock_costs.store_storage_fixed,
                    Stock_Store_Variable: pl.stock_costs.store_storage_variable,
                    Penalty_Stockout: (pl.penalty_costs||{}).stockout,
                    Penalty_Backorder: (pl.penalty_costs||{}).backorder,
                    TotalCost: pl.total_cost,
                    ProfitLoss: pl.profit_loss,
                });
            });
            const headers = Object.keys(rows[0] || { Day: '' });
            const csv = toCsv(rows, headers);
            downloadBlob('profit_loss.csv', csv);
        }

        function displaySummary(summary) {
            if (!summary) { summaryOutput.innerHTML = 'サマリがありません。'; return; }
            const s = summary;
            let html = '';
            const summaryKpisTitle = document.getElementById('summary-kpis-title');
            if (summaryKpisTitle) summaryKpisTitle.innerText = 'サマリKPIs';
            html += '<table><tbody>';
            html += `<tr><th class="kpi-header">計画日数</th><td>${s.planning_days}</td><th class="kpi-header">フィルレート</th><td>${(s.fill_rate*100).toFixed(1)}%</td></tr>`;
            html += `<tr><th class="kpi-header">需要(店舗)</th><td>${formatNumber(s.store_demand_total)}</td><th class="kpi-header">販売(店舗)</th><td>${formatNumber(s.store_sales_total)}</td></tr>`;
            html += `<tr><th class="kpi-header">顧客欠品合計</th><td>${formatNumber(s.customer_shortage_total)}</td><th class="kpi-header">ネットワーク欠品合計</th><td>${formatNumber(s.network_shortage_total)}</td></tr>`;
            html += `<tr><th class="kpi-header">BOピーク</th><td>${formatNumber(s.backorder_peak)} (Day ${s.backorder_peak_day})</td><th class="kpi-header">総収益</th><td>${formatNumber(s.revenue_total)}</td></tr>`;
            html += `<tr><th class="kpi-header">総コスト</th><td>${formatNumber(s.cost_total)}</td><th class="kpi-header">総利益</th><td>${formatNumber(s.profit_total)}</td></tr>`;
            if (typeof s.penalty_total !== 'undefined') {
                html += `<tr><th class="kpi-header">欠品ペナルティ合計</th><td>${formatNumber(s.penalty_stockout_total||0)}</td><th class="kpi-header">BOペナルティ合計</th><td>${formatNumber(s.penalty_backorder_total||0)}</td></tr>`;
                html += `<tr><th class="kpi-header">ペナルティ合計</th><td>${formatNumber(s.penalty_total||0)}</td><th></th><td></td></tr>`;
            }
            html += `<tr><th class="kpi-header">平均日次利益</th><td>${formatNumber(s.profit_per_day_avg)}</td><th></th><td></td></tr>`;
            html += '</tbody></table>';

            // 平均在庫
            if (s.avg_on_hand_by_type) {
                html += '<h3>平均在庫（ノード種別）</h3>';
                html += '<table><thead><tr><th>Type</th><th>Avg On Hand</th></tr></thead><tbody>';
                Object.entries(s.avg_on_hand_by_type).forEach(([k,v]) => {
                    html += `<tr><td style="text-align:left;">${k}</td><td>${formatNumber(v)}</td></tr>`;
                });
                html += '</tbody></table>';
            }

            // 欠品上位品目
            if (s.top_shortage_items && s.top_shortage_items.length) {
                html += '<h3>欠品上位（店舗/品目）</h3>';
                html += '<table><thead><tr><th>Item</th><th>Shortage</th></tr></thead><tbody>';
                s.top_shortage_items.forEach(row => {
                    html += `<tr><td style="text-align:left;">${row.item}</td><td>${formatNumber(row.shortage)}</td></tr>`;
                });
                html += '</tbody></table>';
            }

            summaryOutput.innerHTML = html;
        }

        // --- Event Listeners ---
        runButton.addEventListener('click', runSimulation);
        tabButtons.forEach(button => {
            button.addEventListener('click', (e) => {
                openTab(e, button.dataset.tab);
            });
        });
        nodeFilter.addEventListener('change', applyFilters);
        itemFilter.addEventListener('change', applyFilters);
        dayFrom.addEventListener('change', applyFilters);
        dayTo.addEventListener('change', applyFilters);
        downloadResultsCsvBtn.addEventListener('click', exportResultsCsv);
        downloadPlCsvBtn.addEventListener('click', exportPlCsv);
        if (downloadSummaryCsvBtn) downloadSummaryCsvBtn.addEventListener('click', exportSummaryCsv);

    });
})();
