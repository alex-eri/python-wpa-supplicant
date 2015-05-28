from wpa_supplicant.libcore import WpaSupplicantDriver, Interface, BSS, Network, \
    InterfaceUnknown, InterfaceExists, NotConnected, NetworkUnknown, WpaSupplicant
from twisted.internet.selectreactor import SelectReactor
import time
import mocks
import unittest
import threading
import mock
import Queue


class Task(object):
    def __init__(self, fn, *args, **kwargs):
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def do(self):
        self._fn(*self._args, **self._kwargs)


class ThreadedTaskRunner(threading.Thread):
    _QUIT = object()

    def __init__(self):
        threading.Thread.__init__(self)
        self.setDaemon(True)

        self._tasks = Queue.Queue()

    def run(self):
        while True:
            task = self._tasks.get()
            if task is self._QUIT:
                break
            else:
                if isinstance(task, Task):
                    task.do()

    def stop(self):
        self._tasks.put(self._QUIT)

    def queue(self, task):
        self._tasks.put(task)


class TestWpaSupplicant(unittest.TestCase):
    def setUp(self):
        mocks.init()
        self._taskrunner = ThreadedTaskRunner()
        self._taskrunner.start()
        self._reactor = SelectReactor()
        self._driver = WpaSupplicantDriver(self._reactor)
        self._reactor_thread = threading.Thread(target=self._reactor.run,
                                                kwargs={'installSignalHandlers': 0})
        self._reactor_thread.start()
        time.sleep(0.1)
        self._supplicant = self._driver.connect()

    def tearDown(self):
        self._reactor.disconnectAll()
        self._reactor.sigTerm()
        self._reactor_thread.join()
        self._taskrunner.stop()

    #
    # Helpers
    #
    def _get_interface(self, interface_name):
        return self._supplicant.get_interface(interface_name)

    #
    # Test Driver
    #
    def test_connect(self):
        supplicant = self._driver.connect()
        self.assertIsInstance(supplicant, WpaSupplicant)

    #
    # Test Base
    #
    def test_register_for_signal(self):
        cb = mock.Mock()
        self._supplicant.register_signal('mysig', cb)
        self._supplicant._introspection.fire_signal('mysig', True)
        cb.assert_called_once_with(True)

    def test_register_for_signal_once(self):
        def fire_signal(result):
            time.sleep(1)
            self._supplicant._introspection.fire_signal('mysig', result)

        deferred_queue = self._supplicant.register_signal_once('mysig')
        self._taskrunner.queue(Task(fire_signal, True))
        result = deferred_queue.get()
        self.assertEqual(result, True)

    #
    # Test Supplicant
    #
    def test_get_interface(self):
        interface = self._supplicant.get_interface('wlan0')
        self._supplicant._without_introspection.callRemote.assert_called_with(
            'GetInterface', 'wlan0')
        self.assertTrue(isinstance(interface, Interface))
        self.assertEqual(interface.get_path(), '/fi/w1/wpa_supplicant1/Interfaces/3')

    def test_get_unknown_interface(self):
        self.assertRaises(InterfaceUnknown, self._supplicant.get_interface, 'wlan99')

    def test_create_interface(self):
        interface = self._supplicant.create_interface('wlan0')
        self._supplicant._without_introspection.callRemote.assert_called_with(
            'CreateInterface',
            {'Ifname': 'wlan0'})
        self.assertTrue(isinstance(interface, Interface))
        self.assertEqual(interface.get_path(), '/fi/w1/wpa_supplicant1/Interfaces/3')

    def test_create_interface_already_exists(self):
        self.test_create_interface()
        self.assertRaises(InterfaceExists, self._supplicant.create_interface, 'wlan0')

    def test_remove_interface(self):
        self._supplicant.create_interface('wlan0')
        returnval = self._supplicant.remove_interface(
            '/fi/w1/wpa_supplicant1/Interfaces/3')
        self._supplicant._without_introspection.callRemote.assert_called_with(
            'RemoveInterface',
            '/fi/w1/wpa_supplicant1/Interfaces/3')
        self.assertEqual(returnval, None)

    def test_remove_unknown_interface(self):
        supplicant = self._driver.connect()
        self.assertRaises(InterfaceUnknown, supplicant.remove_interface, 'wlan99')

    def test_get_debug_level(self):
        pass

    def test_get_debug_timestamp(self):
        pass

    def test_get_debug_showkeys(self):
        pass

    def test_get_interfaces(self):
        pass

    def test_get_eap_methods(self):
        pass

    #
    # Test Interface
    #
    def test_interface_scan(self):
        interface = self._get_interface('wlan0')
        scan_results = interface.scan()
        self.assertEqual(scan_results, None)

    def test_interface_blocking_scan(self):
        interface = self._get_interface('wlan0')

        def fire_signal():
            time.sleep(1)
            interface._introspection.fire_signal('ScanDone', True)

        self._taskrunner.queue(Task(fire_signal))
        scan_results = interface.scan(block=True)
        for res in scan_results:
            self.assertTrue(isinstance(res, BSS))
            self.assertEqual(res.get_path(),
                '/fi/w1/wpa_supplicant1/Interfaces/3/BSSs/1234')

    def test_add_network(self):
        interface = self._get_interface('wlan0')
        network = interface.add_network({})
        self.assertTrue(isinstance(network, Network))
        self.assertEqual(network.get_path(), '/fi/w1/wpa_supplicant1/Networks/0')

    def test_remove_network(self):
        interface = self._get_interface('wlan0')
        network = interface.add_network({})
        result = interface.remove_network(network.get_path())
        self.assertEqual(result, None)

    def test_remove_unknown_network(self):
        interface = self._get_interface('wlan0')
        self.assertRaises(NetworkUnknown,
                          interface.remove_network,
                          '/fi/w1/wpa_supplicant1/Networks/44')

    def test_select_network(self):
        interface = self._get_interface('wlan0')
        network = interface.add_network({})
        interface.select_network(network.get_path())
        current_network = interface.get_current_network()
        self.assertEqual(current_network.get_path(), network.get_path())

    def test_get_ifname(self):
        interface = self._get_interface('wlan0')
        self.assertEqual(interface.get_ifname(), 'wlan0')

    def test_get_current_bss(self):
        interface = self._get_interface('wlan0')
        bss = interface.get_current_bss()
        self.assertTrue(isinstance(bss, BSS))

    def test_get_current_network(self):
        interface = self._get_interface('wlan0')
        net = interface.get_current_network()
        self.assertEqual(net, None)

    def test_network_disconnect(self):
        interface = self._get_interface('wlan0')
        network = interface.add_network({})
        interface.select_network(network.get_path())
        interface.disconnect_network()
        self.assertIsNone(interface.get_current_network())

    def test_network_disconnect_not_connected(self):
        interface = self._get_interface('wlan0')
        self.assertRaises(NotConnected, interface.disconnect_network)

    def test_get_networks(self):
        pass

    def test_get_state(self):
        pass

    def test_get_scanning(self):
        pass

    def test_get_scan_interval(self):
        pass

    def test_get_fast_reauth(self):
        pass

    def test_get_all_bss(self):
        pass

    def test_get_driver(self):
        pass

    def test_get_country(self):
        pass

    def test_get_bridge_ifname(self):
        pass

    def test_get_bss_expire_age(self):
        pass

    def test_get_bss_expire_count(self):
        pass

    def test_get_ap_scan(self):
        pass

    #
    # Test BSS
    #
    def test_get_channel(self):
        pass

    def test_get_ssid(self):
        pass

    def test_get_bssid(self):
        pass

    def test_get_frequency(self):
        pass

    def test_get_wpa(self):
        pass

    def test_get_rsn(self):
        pass

    def test_get_ies(self):
        pass

    def test_get_privacy(self):
        interface = self._get_interface('wlan0')
        bss = interface.get_current_bss()
        self.assertEqual(bss.get_privacy(), False)

    def test_get_mode(self):
        pass

    def test_get_rates(self):
        pass

    def test_get_signal_dbm(self):
        interface = self._get_interface('wlan0')
        bss = interface.get_current_bss()
        self.assertEqual(-60, bss.get_signal_dbm())

    def test_get_signal_quality(self):
        interface = self._get_interface('wlan0')
        bss = interface.get_current_bss()
        self.assertEqual(80, bss.get_signal_quality())

    #
    # Test Network
    #
    def test_get_properties(self):
        interface = self._get_interface('wlan0')
        desired_network = interface.add_network({'ssid': 'foo', 'psk': 'bar'})
        interface.select_network(desired_network.get_path())
        curr_network = interface.get_current_network()
        props = curr_network.get_properties()
        self.assertEqual(props['ssid'], 'wdnu-dvt1')

    def test_get_enabled(self):
        pass