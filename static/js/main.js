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
        const runButton = document.querySelector('.run-button');
        const tabButtons = document.querySelectorAll('.tab-button');

        // This variable will hold the complete simulation results
        let fullResultsData = [];

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
                populateFilters(fullResultsData);
                applyFilters(); // This will call displayResultsTable
                displayProfitLossTable(data.profit_loss);

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
        }

        function applyFilters() {
            const selectedNode = nodeFilter.value;
            const selectedItem = itemFilter.value;

            const filteredData = fullResultsData.map(day => {
                const newDay = { ...day, nodes: {} };
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
                    <td>${formatNumber(pl.total_cost)}</td>
                    <td>${formatNumber(pl.profit_loss)}</td>
                </tr>`;
            });

            tableHtml += '</tbody></table>';
            profitLossOutput.innerHTML = tableHtml;
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

    });
})();
