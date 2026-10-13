<?php
// Contract harness: tests the plugin without claiming to run WordPress core.
define('ABSPATH', __DIR__);
$options = array('url' => 'http://127.0.0.1:8800', 'token' => str_repeat('x', 32));
$can = true;
$nonce = true;
$requests = array();
function add_action($name, $callback) {}
function get_option($name, $default) { global $options; return $options; }
function update_option($name, $value, $autoload) { global $options; $options = $value; }
function wp_parse_url($url) { return parse_url($url); }
function current_user_can($capability) { global $can; return $can; }
function wp_die($message) { throw new RuntimeException($message); }
function check_admin_referer($action) { global $nonce; if (!$nonce) { throw new RuntimeException('nonce'); } }
function wp_nonce_field($action) {}
function wp_unslash($value) { return $value; }
function esc_url_raw($value) { return $value; }
function sanitize_key($value) { return preg_replace('/[^a-z0-9_-]/', '', strtolower($value)); }
function sanitize_text_field($value) { return strip_tags($value); }
function esc_html($value) { return htmlspecialchars($value, ENT_QUOTES, 'UTF-8'); }
function esc_attr($value) { return esc_html($value); }
function esc_textarea($value) { return esc_html($value); }
function selected($value, $expected, $echo) { return $value === $expected ? 'selected' : ''; }
function submit_button($title) {}
function wp_json_encode($value, $flags = 0) { return json_encode($value, $flags); }
class WP_Error {
    private $message;
    function __construct($code, $message) { $this->message = $message; }
    function get_error_message() { return $this->message; }
}
function is_wp_error($value) { return $value instanceof WP_Error; }
function wp_remote_retrieve_response_code($value) { return $value['status']; }
function wp_remote_retrieve_body($value) { return $value['body']; }
function wp_remote_request($url, $args) {
    global $requests;
    $requests[] = array($url, $args);
    if (substr($url, -9) === '/v1/games') {
        return array('status' => 200, 'body' => json_encode(array('games' => array(array('id' => 'deadlock', 'title' => '<script>game</script>')), 'default_game' => 'deadlock')));
    }
    return array('status' => 200, 'body' => json_encode(array('text' => '</textarea><script>attack</script>', 'provider' => 'none')));
}
function verify($condition, $message) {
    if (!$condition) { throw new RuntimeException($message); }
}
require __DIR__ . '/../integrations/wordpress/manacost-team/manacost-team.php';

verify(manacost_team_valid_url('https://example.test/api'), 'HTTPS');
verify(!manacost_team_valid_url('http://example.test/api'), 'remote plain HTTP');
verify(!manacost_team_valid_url('https://user:password@example.test'), 'URL credentials');
$_SERVER['REQUEST_METHOD'] = 'GET';
$can = false;
try { manacost_team_tools_page(); throw new RuntimeException('unauthorized page'); } catch (RuntimeException $error) { verify($error->getMessage() === 'Недостаточно прав.', 'capability'); }
verify(count($requests) === 0, 'request before authorization');
$can = true;
$_SERVER['REQUEST_METHOD'] = 'POST';
$_POST = array('source_text' => 'Урон 20%', 'game' => 'deadlock', 'operation' => 'edit', 'genre' => 'game-article');
$nonce = false;
ob_start();
try { manacost_team_tools_page(); throw new RuntimeException('bad nonce accepted'); } catch (RuntimeException $error) { verify($error->getMessage() === 'nonce', 'nonce validation'); }
ob_end_clean();
verify(count($requests) === 1 && $requests[0][1]['method'] === 'GET', 'text submitted before nonce');
$nonce = true;
$requests = array();
ob_start(); manacost_team_tools_page(); $html = ob_get_clean();
verify(count($requests) === 2, 'catalog and editor calls');
$payload = json_decode($requests[1][1]['body'], true);
verify($payload['game'] === 'deadlock' && $payload['genre'] === 'game-article', 'selected context lost');
verify($requests[1][1]['redirection'] === 0, 'credential redirect');
verify(strpos($html, '<script>') === false, 'HTML must be escaped');
verify(strpos($html, str_repeat('x', 32)) === false, 'token leaked into page');
verify(strpos($html, 'Серверный ИИ отключён') !== false, 'provider none is explicit');
$_POST = array('api_url' => 'http://127.0.0.1:8800', 'api_token' => '');
ob_start(); manacost_team_settings_page(); $settings_html = ob_get_clean();
verify($options['token'] === str_repeat('x', 32), 'blank field erased token');
verify(strpos($settings_html, str_repeat('x', 32)) === false, 'settings exposed token');
echo "WordPress plugin contracts passed (stubbed core).\n";
