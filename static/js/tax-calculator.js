/* Recalcula IVA/total al editar base, % o cuota. */
    document.addEventListener("DOMContentLoaded", function () {

        const baseInput = document.querySelector('input[name="base_amount"]');
        const taxPercentageInput = document.querySelector('input[name="tax_percentage"]');
        const taxAmountInput = document.querySelector('input[name="tax_amount"]');
        const totalInput = document.querySelector('input[name="total_amount"]');

        if (!baseInput || !taxPercentageInput || !taxAmountInput || !totalInput) return;

        function parseNumber(value) {
            if (!value) return 0;
            value = value.replace(",", ".");
            return parseFloat(value) || 0;
        }

        function formatNumber(value) {
            return value.toFixed(2);
        }

        function calculateFromPercentage() {
            const base = parseNumber(baseInput.value);
            const percentage = parseNumber(taxPercentageInput.value);

            const tax = base * (percentage / 100);
            const total = base + tax;

            taxAmountInput.value = formatNumber(tax);
            totalInput.value = formatNumber(total);
        }

        function calculateFromTaxAmount() {
            const base = parseNumber(baseInput.value);
            const tax = parseNumber(taxAmountInput.value);

            if (base === 0) return;

            const percentage = (tax / base) * 100;
            const total = base + tax;

            taxPercentageInput.value = formatNumber(percentage);
            totalInput.value = formatNumber(total);
        }

        function calculateFromBase() {
            const base = parseNumber(baseInput.value);
            const percentage = parseNumber(taxPercentageInput.value);

            const tax = base * (percentage / 100);
            const total = base + tax;

            taxAmountInput.value = formatNumber(tax);
            totalInput.value = formatNumber(total);
        }

        taxPercentageInput.addEventListener("input", calculateFromPercentage);
        taxAmountInput.addEventListener("input", calculateFromTaxAmount);
        baseInput.addEventListener("input", calculateFromBase);

    });
    