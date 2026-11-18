"""验证网络分区与心跳丢失的判别规则。"""

from online.diagnosis.agent import detected_codes_from_text


# 网络分区同时产生失联日志时，仍优先判网络。
def test_network_partition_wins_when_datanode_is_retrying():
    text = ("lost datanode datanode3 retrying connect to server: namenode:9000")
    assert detected_codes_from_text(text)[0] == "NETWORK_CONNECTIVITY"


# 只有进程死亡证据时判心跳丢失。
def test_heartbeat_wins_when_no_network_retry():
    text = "lost datanode datanode2 exiting datanode"
    assert detected_codes_from_text(text)[0] == "DN_HEARTBEAT"
