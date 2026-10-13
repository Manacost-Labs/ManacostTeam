<?php
/**
 * Plugin Name: ManacostTeam
 * Description: Редактура и подготовка перевода в стиле Манакоста с выбором игры.
 * Version: 1.0.0
 * Requires PHP: 7.4
 * License: MIT
 */
if (!defined('ABSPATH')) {
    exit;
}

function manacost_team_options() {
    return get_option('manacost_team_connection', array('url' => '', 'token' => ''));
}

function manacost_team_valid_url($url) {
    $parts = wp_parse_url($url);
    if (!$parts || empty($parts['host']) || isset($parts['user']) || isset($parts['pass']) || isset($parts['query']) || isset($parts['fragment'])) {
        return false;
    }
    if (isset($parts['scheme']) && $parts['scheme'] === 'https') {
        return true;
    }
    $local = in_array(strtolower($parts['host']), array('localhost', '127.0.0.1', '[::1]'), true);
    return isset($parts['scheme']) && $parts['scheme'] === 'http' && ($local || (defined('MANACOST_ALLOW_PRIVATE_HTTP') && MANACOST_ALLOW_PRIVATE_HTTP));
}

function manacost_team_api($route, $payload = null) {
    $options = manacost_team_options();
    if (empty($options['token']) || !manacost_team_valid_url($options['url'])) {
        return new WP_Error('manacost_connection', 'Администратор должен настроить URL и токен ManacostTeam.');
    }
    $args = array(
        'method' => $payload === null ? 'GET' : 'POST',
        'timeout' => 160,
        'redirection' => 0,
        'limit_response_size' => 4 * 1024 * 1024,
        'headers' => array('Authorization' => 'Bearer ' . $options['token'], 'Content-Type' => 'application/json'),
    );
    if ($payload !== null) {
        $args['body'] = wp_json_encode($payload, JSON_UNESCAPED_UNICODE);
    }
    $response = wp_remote_request(rtrim($options['url'], '/') . $route, $args);
    if (is_wp_error($response)) {
        return new WP_Error('manacost_unavailable', 'Нет ответа от ManacostTeam. Проверьте адрес, доступность сервера и таймаут PHP.');
    }
    $status = wp_remote_retrieve_response_code($response);
    $body = json_decode(wp_remote_retrieve_body($response), true);
    if ($status < 200 || $status >= 300 || !is_array($body)) {
        return new WP_Error('manacost_response', 'ManacostTeam отклонил запрос (HTTP ' . intval($status) . '). Проверьте токен, игру, жанр и сборку.');
    }
    return $body;
}

function manacost_team_games() {
    $result = manacost_team_api('/v1/games');
    if (is_wp_error($result)) {
        return $result;
    }
    if (empty($result['games']) || !is_array($result['games'])) {
        return new WP_Error('manacost_catalog', 'Сервер не вернул каталог игр.');
    }
    $games = array();
    foreach ($result['games'] as $game) {
        if (!is_array($game) || !isset($game['id'], $game['title']) || !is_string($game['id']) || !is_string($game['title']) || !preg_match('/^[a-z0-9]+(?:-[a-z0-9]+)*$/', $game['id'])) {
            return new WP_Error('manacost_catalog', 'Некорректный каталог игр.');
        }
        $games[$game['id']] = $game['title'];
    }
    return array('games' => $games, 'default_game' => isset($result['default_game']) ? $result['default_game'] : 'hearthstone');
}

function manacost_team_settings_page() {
    if (!current_user_can('manage_options')) {
        wp_die('Недостаточно прав.');
    }
    $notice = '';
    if ($_SERVER['REQUEST_METHOD'] === 'POST') {
        check_admin_referer('manacost_team_settings');
        $url = isset($_POST['api_url']) && is_string($_POST['api_url']) ? esc_url_raw(trim(wp_unslash($_POST['api_url']))) : '';
        $token = isset($_POST['api_token']) && is_string($_POST['api_token']) ? trim(wp_unslash($_POST['api_token'])) : '';
        $old = manacost_team_options();
        if (!manacost_team_valid_url($url) || ($token !== '' && !preg_match('/^[A-Za-z0-9_-]{32,}$/', $token))) {
            $notice = 'Нужны корректный URL и токен из файла secrets/api-token.txt. Внешнее подключение требует HTTPS.';
        } elseif ($token === '' && ($url !== $old['url'] || empty($old['token']))) {
            $notice = 'Для нового адреса укажите токен заново.';
        } else {
            update_option('manacost_team_connection', array('url' => rtrim($url, '/'), 'token' => $token !== '' ? $token : $old['token']), false);
            $notice = 'Подключение сохранено. Поле токена не отображает сохранённый секрет.';
        }
    }
    $options = manacost_team_options();
    echo '<div class="wrap"><h1>Подключение ManacostTeam</h1><p>' . esc_html($notice) . '</p>';
    echo '<form method="post">';
    wp_nonce_field('manacost_team_settings');
    echo '<p><label>URL API <input type="url" name="api_url" class="regular-text" required value="' . esc_attr($options['url']) . '" placeholder="http://127.0.0.1:8800"></label></p>';
    echo '<p><label>Токен API <input type="password" name="api_token" class="regular-text" autocomplete="new-password" value=""></label></p>';
    echo '<p>Оставьте токен пустым, чтобы сохранить прежний при том же адресе. Токен хранится в базе WordPress и доступен администраторам сервера.</p>';
    submit_button('Сохранить подключение');
    echo '</form></div>';
}

function manacost_team_tools_page() {
    if (!current_user_can('edit_posts')) {
        wp_die('Недостаточно прав.');
    }
    $catalog = manacost_team_games();
    echo '<div class="wrap"><h1>ManacostTeam</h1><p>Стиль Манакоста общий. Термины и проверки выбираются по игре. Исходный текст и публикации не изменяются.</p>';
    if (is_wp_error($catalog)) {
        echo '<p>' . esc_html($catalog->get_error_message()) . '</p></div>';
        return;
    }
    $text = isset($_POST['source_text']) && is_string($_POST['source_text']) ? wp_unslash($_POST['source_text']) : '';
    $game = isset($_POST['game']) && is_string($_POST['game']) ? sanitize_text_field(wp_unslash($_POST['game'])) : $catalog['default_game'];
    $patch = isset($_POST['patch']) && is_string($_POST['patch']) ? sanitize_text_field(wp_unslash($_POST['patch'])) : '';
    $product = isset($_POST['product']) && is_string($_POST['product']) ? sanitize_text_field(wp_unslash($_POST['product'])) : '';
    $genres = array('game-article' => 'Статья', 'game-guide' => 'Гайд', 'news' => 'Новость');
    $genre = isset($_POST['genre']) && is_string($_POST['genre']) ? sanitize_key(wp_unslash($_POST['genre'])) : 'game-article';
    $result = null;
    if ($_SERVER['REQUEST_METHOD'] === 'POST') {
        check_admin_referer('manacost_team_run');
        $operation = isset($_POST['operation']) && is_string($_POST['operation']) ? sanitize_key(wp_unslash($_POST['operation'])) : '';
        $routes = array('analyze' => '/v1/editor/analyze', 'edit' => '/v1/editor/edit', 'prepare' => '/v1/translate/prepare');
        if (!isset($catalog['games'][$game], $routes[$operation], $genres[$genre]) || !trim($text) || strlen($text) > 400000) {
            $result = new WP_Error('manacost_input', 'Выберите игру и действие; текст должен быть непустым и не больше 400 КБ.');
        } else {
            $payload = array('text' => $text, 'game' => $game);
            if ($patch !== '') {
                $payload['patch'] = $patch;
            }
            if ($operation === 'prepare' && $game === 'world-of-warcraft') {
                $payload['product'] = $product;
            }
            if ($operation === 'edit') {
                $payload['mode'] = 'edit';
            }
            if ($operation !== 'prepare') {
                $payload['genre'] = $genre;
            }
            $result = manacost_team_api($routes[$operation], $payload);
        }
    }
    echo '<form method="post">';
    wp_nonce_field('manacost_team_run');
    echo '<p><label>Игра <select name="game">';
    foreach ($catalog['games'] as $id => $title) {
        echo '<option value="' . esc_attr($id) . '" ' . selected($game, $id, false) . '>' . esc_html($title) . '</option>';
    }
    echo '</select></label></p>';
    echo '<p><label>Жанр <select name="genre">';
    foreach ($genres as $id => $title) {
        echo '<option value="' . esc_attr($id) . '" ' . selected($genre, $id, false) . '>' . esc_html($title) . '</option>';
    }
    echo '</select></label></p>';
    echo '<p><label>Патч / точная сборка <input name="patch" maxlength="80" value="' . esc_attr($patch) . '"></label> <label>Продукт WoW <input name="product" maxlength="80" value="' . esc_attr($product) . '" placeholder="retail"></label></p>';
    echo '<p>Для подготовки перевода укажите сборку; для WoW также продукт. Переводчик подготовит термины и инструкцию для агента, а не готовый перевод.</p>';
    echo '<textarea name="source_text" rows="16" class="large-text" required>' . esc_textarea($text) . '</textarea>';
    echo '<p><button class="button" name="operation" value="analyze">Проверить текст</button> <button class="button" name="operation" value="prepare">Подготовить перевод</button> <button class="button" name="operation" value="edit">Редактировать через серверный ИИ</button></p></form>';
    if (is_wp_error($result)) {
        echo '<p>' . esc_html($result->get_error_message()) . '</p>';
    } elseif (is_array($result)) {
        if (isset($result['provider']) && $result['provider'] === 'none') {
            echo '<p>Серверный ИИ отключён. Выполнены доступные проверки; для автоматической редактуры настройте провайдера на сервере.</p>';
        }
        if (isset($result['text']) && is_string($result['text'])) {
            echo '<h2>Результат для проверки и копирования</h2><textarea rows="16" class="large-text" readonly>' . esc_textarea($result['text']) . '</textarea>';
        }
        echo '<h2>Отчёт</h2><textarea rows="16" class="large-text code" readonly>' . esc_textarea(wp_json_encode($result, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE)) . '</textarea>';
    }
    echo '</div>';
}

add_action('admin_menu', function () {
    add_options_page('ManacostTeam', 'ManacostTeam', 'manage_options', 'manacost-team-connection', 'manacost_team_settings_page');
    add_management_page('ManacostTeam', 'ManacostTeam', 'edit_posts', 'manacost-team', 'manacost_team_tools_page');
});
