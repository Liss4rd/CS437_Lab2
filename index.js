const net = require("net");

const SERVER_IP = "192.168.1.167";
const SOCKET_PORT = 65432;
const VIDEO_PORT = 8081;

let client = null;
let rxBuffer = "";

function connectSocket() {
    if (client && !client.destroyed) {
        return;
    }

    client = new net.Socket();

    client.connect(SOCKET_PORT, SERVER_IP, () => {
        console.log(`Connected to socket server at ${SERVER_IP}:${SOCKET_PORT}`);
    });

    client.on("data", (data) => {
        rxBuffer += data.toString("utf8");

        while (rxBuffer.includes("\n")) {
            const newlineIndex = rxBuffer.indexOf("\n");
            const line = rxBuffer.slice(0, newlineIndex).trim();
            rxBuffer = rxBuffer.slice(newlineIndex + 1);

            if (line.length > 0) {
                handleIncomingLine(line);
            }
        }
    });

    client.on("close", () => {
        console.log("Socket connection closed");
    });

    client.on("error", (error) => {
        console.error("Socket error:", error);
    });
}

function handleIncomingLine(line) {
    console.log("RX:", line);

    if (line.startsWith("ACK:")) {
        return;
    }

    try {
        const data = JSON.parse(line);

        if (data.moving !== undefined) {
            document.getElementById("direction").innerText = capitalize(data.moving);
        }

        if (data.obstacle_dist_cm !== undefined) {
            document.getElementById("obstacleDistance").innerText = `${data.obstacle_dist_cm} cm`;
        }

        if (data.cliff_detected !== undefined) {
            document.getElementById("cliffDetected").innerText = data.cliff_detected ? "Yes" : "No";
        }

        if (data.cpu_temp !== undefined) {
            document.getElementById("cpuTempValue").innerText = `${Number(data.cpu_temp).toFixed(1)} \u00B0C`;
        }
    } catch (error) {
        console.error("Failed to parse telemetry JSON:", error, line);
    }
}

function startVideo() {
    const feed = document.getElementById("cameraFeed");
    const btn = document.getElementById("startBtn");

    feed.src = `http://${SERVER_IP}:${VIDEO_PORT}/stream`;
    feed.style.display = "block";
    btn.style.display = "none";
}

function sendDirection(direction) {
    console.log("Button pressed:", direction);

    if (!client || client.destroyed) {
        console.error("Socket is not connected");
        return;
    }

    client.write(direction + "\n");

    const directionText = document.getElementById("direction");
    if (directionText) {
        directionText.innerText = capitalize(direction);
    }
}

function capitalize(text) {
    if (!text) return "";
    return text.charAt(0).toUpperCase() + text.slice(1);
}

window.onload = function () {
    connectSocket();
};

window.sendDirection = sendDirection;
window.startVideo = startVideo;
