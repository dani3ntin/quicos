import * as moment from "moment";
import "whatwg-fetch";

import {
    IChronografDashboardResult,
    IGrafanaStatistic,
    IInfluxComparative,
    IInfluxHistogram,
    IInfluxNames,
    IInfluxNamesAndSuffixes,
    IInfluxStatistics,
} from "../interfaces/influx.interface";
import {IScenarioInstance} from "../interfaces/scenarioInstance.interface";
import {checkStatus, doApiCall} from "./common";


export function getStatisticsNames(projectName: string): Promise<IInfluxNames> {
    return doApiCall("/statistic/" + projectName)
        .then((response: Response) => response.json<IInfluxNames>());
};


export function getStatisticsNamesAndSuffixes(jobID: number): Promise<IInfluxNamesAndSuffixes> {
    return doApiCall("/statistic/" + jobID)
        .then((response: Response) => response.json<IInfluxNamesAndSuffixes>());
};


export function getStatisticsOrigin(jobID: number): Promise<Date> {
    return doApiCall("/statistic/" + jobID + "/?origin")
        .then((response: Response) => response.json<number>())
        .then((response: number) => new Date(response))
        .catch(() => new Date());
};


const buildStatisticsRoute = (jobID: number, statName: string, suffix: string): string => {
    const route = `/statistic/${jobID}?name=${statName}`;
    if (!suffix) {
        return route;
    }
    return `${route}&suffix=${suffix}`;
};


export function getStatistics(jobID: number, statName: string, suffix: string, origin?: number): Promise<IInfluxStatistics> {
    let route = buildStatisticsRoute(jobID, statName, suffix);
    if (origin || origin === 0) {
        route += "&origin=" + origin;
    }
    return doApiCall(route).then((response: Response) => response.json<IInfluxStatistics>());
};


export function getStatisticsHistogram(jobID: number, statName: string, suffix: string, buckets: number): Promise<IInfluxHistogram> {
    const route = buildStatisticsRoute(jobID, statName, suffix) + "&histogram=" + buckets;
    return doApiCall(route).then((response: Response) => response.json<IInfluxHistogram>());
};


export function getStatisticsComparative(jobID: number, statName: string, suffix: string): Promise<IInfluxComparative> {
    const route = buildStatisticsRoute(jobID, statName, suffix) + "&comparative";
    return doApiCall(route).then((response: Response) => response.json<IInfluxComparative>());
};


interface IGraphIntermediate {
    agent: string;
    name: string;
    jobId: number;
    unit: string;
    targets: string[];
};


export function postGrafanaDashboard(instance: IScenarioInstance, statistics: IGrafanaStatistic[], grouped: boolean): Promise<IChronografDashboardResult> {
    const graphs: IGraphIntermediate[] = [];
    let targets = null;

    statistics.sort((a: IGrafanaStatistic, b: IGrafanaStatistic): number => {
        if (a.jobId === b.jobId) {
            if (a.unit === b.unit) {
                return 0;
            }
            return a.unit < b.unit ? -1 : 1;
        }
        return a.jobId - b.jobId;
    }).forEach((statistic: IGrafanaStatistic, index: number, array: IGrafanaStatistic[]) => {
        const {jobAgent, jobName, jobId, statName, unit} = statistic;
        if (!grouped || index === 0 || array[index - 1].jobId !== jobId || array[index - 1].unit !== unit) {
            targets = [];
            graphs.push({
                agent: jobAgent,
                name: jobName,
                jobId,
                targets,
                unit,
            });
        }
        targets.push(statName);
    });

    const dashboard = {
        cells: graphs.map((graph: IGraphIntermediate, index: number) => {
            let yLabel = "Valore di prova per Y";
            let graphName = "Default";
	    let isHistogram = graph.name.toLowerCase().includes("fairness");

            if (graph.targets.some(target => target.includes("fairness"))) { yLabel = ""; graphName = "Fairness"; }
            if (graph.targets.some(target => target.includes("average_rtt"))) { yLabel = "Average RTT (ms)"; graphName = "Average RTT"; }
            if (graph.targets.some(target => target.includes("average_throughput"))) { yLabel = "Average Throughput (bytes/ms)"; graphName = "Average Throughput"; }
            if (graph.targets.some(target => target.includes("min_rtt"))) { yLabel = "Min RTT (ms)"; graphName = "Min RTT"; }
            if (graph.targets.some(target => target.includes("smoothed_rtt"))) { yLabel = "Smoothed RTT (ms)"; graphName = "Smoothed RTT"; }
            if (graph.targets.some(target => target.includes("smoothed_rtt"))) { yLabel = "Smoothed RTT (ms)"; graphName = "Smoothed RTT"; }
            if (graph.targets.some(target => target.includes("latest_rtt"))) { yLabel = "Latest RTT (ms)"; graphName = "Latest RTT"; }
            if (graph.targets.some(target => target.includes("rtt_variance"))) { yLabel = "RTT Variance (ms)"; graphName = "RTT variance"; }
            if (graph.targets.some(target => target.includes("pto_count"))) { yLabel = "PTO Count"; graphName = "Probe timeout events Count"; }
            if (graph.targets.some(target => target.includes("congestion_window"))) { yLabel = "Congestion Window (bytes)"; graphName = "Congestion window"; }
            if (graph.targets.some(target => target.includes("bytes_in_flight"))) { yLabel = "Bytes in Flight (bytes)"; graphName = "Bytes in Flight"; }
            
            const isSingleStat = graph.targets.some(target =>["fairness", "average_rtt", "average_throughput"].some(keyword => target.includes(keyword)));

            return {
                h: 4,
                name: `${graphName} (#${graph.jobId})`,
                type: isSingleStat ? "single-stat" : "line",
                queries: graph.targets.map((statName: string, id: number) => ({
                    query: [
                        `SELECT "${statName}" FROM "openbach"."openbach"."${graph.name}"`,
                        `WHERE time > ${moment(instance.start_date).valueOf()}ms`,
                        `AND "@job_instance_id"='${graph.jobId}' GROUP BY "@suffix" FILL(null)`,
                    ].join(" "),
                    source: "",
                    text: `${statName} (${graph.unit})`,
                    type: "influxql",
                })),
                axes: {
                    x: {
                        base: "10",
                        bounds: ["", ""],
                        label: "Time",
                        prefix: "",
                        scale: "linear",
                        suffix: "",
                    },
                    y: {
                        base: "",
                        bounds: ["", ""],
                        label: yLabel,
                        prefix: "",
                        scale: "linear",
                        suffix: "",
                    },
                    y2: {
                        base: "",
                        bounds: ["", ""],
                        label: "",
                        prefix: "",
                        scale: "",
                        suffix: "",
                    },
                },
                w: 12,
                x: 0,
                y: 4 * index,
            };
        }),
        name: `Scenario instance #${instance.owner_scenario_instance_id}`,
    };

    const params: RequestInit = {
        body: JSON.stringify(dashboard),
        headers: {
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method: "POST",
    };

    return fetch("/chronograf/api/dashboards", params)
        .then(checkStatus)
        .then((response: Response) => new Promise<IChronografDashboardResult>((resolve) => resolve(response.json<IChronografDashboardResult>())));
};
