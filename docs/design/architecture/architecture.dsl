workspace "Polyquack" "Quantitative research on funding between Polymarket Perps and Hyperliquid, on paper." {

    !identifiers hierarchical

    model {
        author = person "Author" "Sole operator: preregisters methods, reviews the dashboard and decides visibility."
        visitor = person "Visitor" "Reads the read-only public view."

        polymarket = softwareSystem "Polymarket Perps" "Perpetual futures platform. Public REST API and live channel." "External"
        hyperliquid = softwareSystem "Hyperliquid" "Perpetual futures platform. Public REST API and live channel." "External"
        hosting = softwareSystem "Static hosting" "Serves the public site; has no access to the database." "External"

        polyquack = softwareSystem "Polyquack" {
            ingestion = container "Ingestion" "Discovers instruments and pairs them. Listens to the live order book channels and stores one snapshot per minute. Requests funding, parameters and fees over REST. Every minute it requests the mark and index prices of all instruments in a single request per platform (ADR-006). Recovers history and records gaps." "Python, long-running service"
            database = container "Database" "Readings, gaps, pairs, preregistrations, runs, paper trades and verdicts. Readings are append-only." "SQLite in WAL mode" "Database"
            evaluator = container "Evaluator" "Every hour it runs the live variants (E1 on paper). On demand, it re-evaluates a variant over stored data. Issues verdicts when the horizon is reached." "Python, scheduled task and command line"
            dashboard = container "Private dashboard" "Ingestion status, paper positions, net profit with breakdown and progress toward the verdict. Only listens inside the VM." "Python, web application"
            exporter = container "Public exporter" "Generates the static site with only what is marked public." "Python, scheduled task"
        }

        polyquack.ingestion -> polymarket "Reads instruments, funding, order book, mark and index price" "WebSocket and HTTPS"
        polyquack.ingestion -> hyperliquid "Reads instruments, funding, order book, mark and index price" "WebSocket and HTTPS"
        polyquack.ingestion -> polyquack.database "Appends readings and gaps"
        polyquack.evaluator -> polyquack.database "Reads readings up to the hour of each decision; writes decisions, paper trades and verdicts"
        polyquack.dashboard -> polyquack.database "Reads"
        polyquack.exporter -> polyquack.database "Reads only what is marked public"
        polyquack.exporter -> hosting "Publishes the generated site" "HTTPS"
        author -> polyquack.dashboard "Browses through an SSH tunnel" "HTTPS over SSH"
        author -> polyquack.evaluator "Preregisters variants and requests re-evaluations" "Command line over SSH"
        visitor -> hosting "Reads the public view" "HTTPS"

        deploymentEnvironment "Production" {
            deploymentNode "Author's server" "Always on, stable network (ADR-001)" "Local physical machine" {
                deploymentNode "VM" "" "Linux" {
                    containerInstance polyquack.ingestion
                    containerInstance polyquack.database
                    containerInstance polyquack.evaluator
                    containerInstance polyquack.dashboard
                    containerInstance polyquack.exporter
                }
            }
            deploymentNode "Internet" {
                softwareSystemInstance hosting
                softwareSystemInstance polymarket
                softwareSystemInstance hyperliquid
            }
        }
    }

    views {
        systemContext polyquack "Context" {
            include *
            autoLayout lr
        }
        container polyquack "Containers" {
            include *
            autoLayout lr
        }
        deployment polyquack "Production" "Deployment" {
            include *
            autoLayout lr
        }
        styles {
            element "External" {
                background #999999
                color #ffffff
            }
            element "Database" {
                shape Cylinder
            }
        }
    }
}
